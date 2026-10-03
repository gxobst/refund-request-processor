import asyncio
import csv
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
import io
import json
from pathlib import Path
import re
from typing import Any
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.agents.proof_notifier import generate_reviewer_proof_email
from app.auth.rbac import require_supervisor_role
from app.db.repository import RefundNotFoundError, RefundRepository
from app.graph.runner import resume_refund_workflow, run_refund_workflow
from app.schemas.order import ORDER_ID_PATTERN
from app.services.broadcaster import broadcaster
from app.schemas.refund import (
    EvidenceItem,
    RefundClarificationRequest,
    RefundCreateRequest,
    RefundCreateResponse,
    RefundOverrideRequest,
    RefundRecord,
    RefundStatus,
    ReviewerProofRequest,
)
from app.services.storage import EvidenceStorageService, get_evidence_storage_service

router = APIRouter(prefix="/refunds", tags=["refunds"])

HTTP_413_STATUS = 413
HTTP_422_STATUS = 422


def _parse_multipart_request(
    content_type_header: str, body_bytes: bytes
) -> tuple[dict[str, str], list[UploadFile]]:
    """Parse multipart/form-data body using standard library email parser.

    Constructs msg_bytes with the case-preserved Content-Type header so BytesParser
    matches mixed-case multipart boundaries against boundary delimiters in the payload.
    """
    fields: dict[str, str] = {}
    files: list[UploadFile] = []

    msg_bytes = f"Content-Type: {content_type_header}\r\n\r\n".encode("latin1", errors="replace") + body_bytes
    msg = BytesParser(policy=default).parsebytes(msg_bytes)

    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        content_type = part.get_content_type()
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = b""

        if filename is not None:
            uf = UploadFile(
                file=io.BytesIO(payload),
                size=len(payload),
                filename=filename,
                headers={"content-type": content_type},
            )
            files.append(uf)
        elif name:
            fields[name] = payload.decode("utf-8", errors="replace")

    return fields, files


def get_repository() -> RefundRepository:
    """Dependency provider for RefundRepository."""
    return RefundRepository()


@router.get(
    "",
    response_model=list[RefundRecord],
    status_code=status.HTTP_200_OK,
    summary="List refund requests with optional status filtering",
)
async def list_refund_requests(
    status: RefundStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    repo: RefundRepository = Depends(get_repository),
) -> list[RefundRecord]:
    """Retrieve refund queue records with optional status filtering."""
    return repo.list_refund_requests(status=status, limit=limit)


REFUND_CREATE_OPENAPI_EXTRA: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "pattern": "^ORD-\\d{4}$",
                            "description": "Identifier of the order to evaluate.",
                        },
                        "customer_request_text": {
                            "type": "string",
                            "description": "Customer explanation for the refund request.",
                        },
                    },
                    "required": ["order_id", "customer_request_text"],
                }
            },
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "pattern": "^ORD-\\d{4}$",
                            "description": "Identifier of the order to evaluate.",
                        },
                        "customer_request_text": {
                            "type": "string",
                            "description": "Customer explanation for the refund request.",
                        },
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "Optional supporting evidence image file.",
                        },
                    },
                    "required": ["order_id", "customer_request_text"],
                }
            },
        },
    }
}


@router.post(
    "",
    response_model=RefundCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a refund request for automated evaluation",
    openapi_extra=REFUND_CREATE_OPENAPI_EXTRA,
)
async def submit_refund_request(
    request: Request,
    background_tasks: BackgroundTasks,
    repo: RefundRepository = Depends(get_repository),
    storage_service: EvidenceStorageService = Depends(get_evidence_storage_service),
) -> RefundCreateResponse:
    """Accept and initiate asynchronous multi-agent processing for a refund request."""
    raw_content_type = request.headers.get("content-type", "")
    content_type_lower = raw_content_type.lower()
    order_id: str | None = None
    customer_request_text: str | None = None
    uploaded_file: UploadFile | None = None

    if "multipart/form-data" in content_type_lower:
        body = await request.body()
        form_fields, form_files = _parse_multipart_request(raw_content_type, body)
        raw_order_id = form_fields.get("order_id")
        if raw_order_id is None or not str(raw_order_id).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'order_id' cannot be blank or empty.",
            )
        order_id = str(raw_order_id).strip()
        if not re.match(ORDER_ID_PATTERN, order_id):
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail=f"Invalid order_id '{order_id}'. Must match pattern '{ORDER_ID_PATTERN}'.",
            )
        raw_text = form_fields.get("customer_request_text")
        if raw_text is None or not str(raw_text).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'customer_request_text' cannot be blank or empty.",
            )
        customer_request_text = str(raw_text).strip()
        if form_files:
            uploaded_file = form_files[0]
    elif "application/x-www-form-urlencoded" in content_type_lower:
        from urllib.parse import parse_qs

        body = await request.body()
        parsed = parse_qs(body.decode("utf-8", errors="replace"))
        raw_order_id_list = parsed.get("order_id", [])
        raw_order_id = raw_order_id_list[0] if raw_order_id_list else None
        if raw_order_id is None or not str(raw_order_id).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'order_id' cannot be blank or empty.",
            )
        order_id = str(raw_order_id).strip()
        if not re.match(ORDER_ID_PATTERN, order_id):
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail=f"Invalid order_id '{order_id}'. Must match pattern '{ORDER_ID_PATTERN}'.",
            )
        raw_text_list = parsed.get("customer_request_text", [])
        raw_text = raw_text_list[0] if raw_text_list else None
        if raw_text is None or not str(raw_text).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'customer_request_text' cannot be blank or empty.",
            )
        customer_request_text = str(raw_text).strip()
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Invalid or missing request body.",
            )
        try:
            payload = RefundCreateRequest.model_validate(body)
            order_id = payload.order_id
            customer_request_text = payload.customer_request_text
        except Exception as err:
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail=str(err),
            )

    refund_id = f"ref_{uuid.uuid4().hex[:12]}"
    evidence: list[dict[str, Any]] = []

    if uploaded_file is not None:
        filename = uploaded_file.filename or "evidence_file"
        ext = Path(filename).suffix.lower()
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        if ext not in allowed_extensions:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "type": "urn:problem:bad-request",
                    "title": "Bad Request",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "detail": f"Disallowed file extension '{ext}'. Allowed extensions are: {sorted(allowed_extensions)}",
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )
        file_bytes = await uploaded_file.read()
        file_content_type = uploaded_file.content_type or ""
        try:
            storage_service.validate_file(file_bytes=file_bytes, content_type=file_content_type)
        except ValueError as e:
            msg = str(e)
            if "exceeds maximum allowed limit" in msg:
                return JSONResponse(
                    status_code=HTTP_413_STATUS,
                    content={
                        "type": "urn:problem:payload-too-large",
                        "title": "Payload Too Large",
                        "status": HTTP_413_STATUS,
                        "detail": msg,
                        "instance": request.url.path,
                    },
                    media_type="application/problem+json",
                )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "type": "urn:problem:bad-request",
                    "title": "Bad Request",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "detail": msg,
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )

        saved_meta = storage_service.save_file(
            file_bytes=file_bytes,
            filename=filename,
            content_type=file_content_type,
            refund_id=refund_id,
            order_id=order_id,
        )
        evidence.append(saved_meta)

    # 1. Create initial pending record in DynamoDB
    try:
        record = repo.create_refund_request(
            order_id=order_id,
            customer_request_text=customer_request_text,
            evidence=evidence,
        )
    except TypeError:
        record = repo.create_refund_request(
            order_id=order_id,
            customer_request_text=customer_request_text,
        )

    # 2. Schedule async LangGraph workflow execution in the background
    background_tasks.add_task(
        run_refund_workflow,
        refund_id=record.refund_id,
        order_id=record.order_id,
        customer_request_text=record.customer_request_text,
        repository=repo,
        evidence=record.evidence,
    )

    # 3. Broadcast refund creation update
    await broadcaster.publish(
        "refund_update",
        {
            "refund_id": record.refund_id,
            "order_id": record.order_id,
            "status": "pending",
        },
    )

    # 4. Return accepted response
    return RefundCreateResponse(
        refund_id=record.refund_id,
        order_id=record.order_id,
        status=record.status,
        created_at=record.created_at,
    )


@router.post(
    "/{refund_id}/override",
    response_model=RefundRecord,
    status_code=status.HTTP_200_OK,
    summary="Manually override a refund request decision",
)
async def override_refund_decision(
    refund_id: str,
    payload: RefundOverrideRequest,
    request: Request,
    role: str = Depends(require_supervisor_role),
    repo: RefundRepository = Depends(get_repository),
) -> RefundRecord:
    """Apply a human operator decision override to a refund request."""
    operator_id = request.headers.get("X-User-Id", "").strip() or "supervisor"
    try:
        updated = repo.apply_override(
            refund_id=refund_id,
            override_decision=payload.override_decision,
            override_reason=payload.reason,
            overridden_by=operator_id,
        )
    except (RefundNotFoundError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found",
        )
    await broadcaster.publish(
        "refund_update",
        {
            "refund_id": refund_id,
            "status": updated.status,
            "override_decision": payload.override_decision,
            "reasoning": payload.reason,
            "overridden_by": operator_id,
        },
    )
    return updated


@router.get(
    "/events",
    status_code=status.HTTP_200_OK,
    summary="Subscribe to real-time refund server-sent events (SSE)",
)
async def subscribe_refund_events(
    request: Request,
    limit: int | None = Query(default=None, ge=1),
) -> StreamingResponse:
    """Stream real-time refund update events to connected SSE clients."""
    async def event_generator():
        queue = await broadcaster.subscribe()
        yielded_count = 0
        try:
            # Send initial ping event to establish connection and keep proxies from timing out
            yield "event: ping\ndata: {}\n\n"
            yielded_count += 1
            if limit is not None and yielded_count >= limit:
                return

            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    event_name = item.get("event", "message")
                    data_json = json.dumps(item.get("data", {}))
                    yield f"event: {event_name}\ndata: {data_json}\n\n"
                    yielded_count += 1
                    if limit is not None and yielded_count >= limit:
                        return
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            await broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


CSV_EXPORT_HEADERS = [
    "Refund ID",
    "Order ID",
    "Status",
    "Decision",
    "Category",
    "Refund Amount",
    "Confidence Score",
    "Customer Request",
    "Decision Reasoning",
    "Override Decision",
    "Override Reason",
    "Created At",
    "Updated At",
]


def _format_export_csv(records: list[RefundRecord]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_EXPORT_HEADERS)

    for r in records:
        rec_dict = r.model_dump() if hasattr(r, "model_dump") else r.__dict__
        refund_amount = rec_dict.get("refund_amount")
        if refund_amount is None:
            refund_amount = rec_dict.get("order_amount")

        conf_score = getattr(r, "confidence_score", None)
        confidence_str = "" if conf_score is None else str(conf_score)
        amount_str = "" if refund_amount is None else str(refund_amount)

        writer.writerow([
            getattr(r, "refund_id", "") or "",
            getattr(r, "order_id", "") or "",
            getattr(r, "status", "") or "",
            getattr(r, "decision", "") or "",
            getattr(r, "category", "") or "",
            amount_str,
            confidence_str,
            getattr(r, "customer_request_text", "") or "",
            getattr(r, "reasoning", "") or "",
            getattr(r, "override_decision", "") or "",
            getattr(r, "override_reason", "") or "",
            getattr(r, "created_at", "") or "",
            getattr(r, "updated_at", "") or "",
        ])

    return output.getvalue()


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export refund queue records as CSV or JSON",
)
async def export_refund_requests(
    request: Request,
    format: str = Query(default="csv"),
    status: RefundStatus | None = Query(default=None),
    repo: RefundRepository = Depends(get_repository),
) -> Response:
    """Export refund requests matching the optional status filter in CSV or JSON format."""
    normalized_format = format.strip().lower() if format else ""
    if normalized_format not in ("csv", "json"):
        raise HTTPException(
            status_code=HTTP_422_STATUS,
            detail={
                "type": "urn:problem:validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": f"Invalid export format '{format}'. Supported formats are 'csv' and 'json'.",
                "instance": request.url.path,
                "invalidParams": [{"name": "format", "reason": "Must be 'csv' or 'json'"}],
            },
        )

    records = repo.list_refund_requests(status=status, limit=10000)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    status_str = status.strip().lower() if status else "all"

    if normalized_format == "csv":
        filename = f"refunds-{status_str}-{timestamp}.csv"
        csv_content = _format_export_csv(records)
        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        filename = f"refunds-{status_str}-{timestamp}.json"
        json_data = [
            r.model_dump(mode="json") if hasattr(r, "model_dump") else r
            for r in records
        ]
        json_content = json.dumps(json_data, indent=2)
        return Response(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.get(
    "/{refund_id}",
    response_model=RefundRecord,
    status_code=status.HTTP_200_OK,
    summary="Poll or inspect refund request status and decision",
)
async def get_refund_request_by_id(
    refund_id: str,
    repo: RefundRepository = Depends(get_repository),
) -> RefundRecord:
    """Retrieve refund request details, workflow status, and agent decision."""
    record = repo.get_refund_request(refund_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found",
        )
    return record


EVIDENCE_UPLOAD_OPENAPI_EXTRA: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "Evidence image file.",
                        }
                    },
                    "required": ["file"],
                }
            }
        },
    }
}


@router.post(
    "/{refund_id}/evidence",
    response_model=RefundRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Upload photo evidence for a refund request",
    openapi_extra=EVIDENCE_UPLOAD_OPENAPI_EXTRA,
)
async def upload_refund_evidence(
    refund_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    repo: RefundRepository = Depends(get_repository),
    storage_service: EvidenceStorageService = Depends(get_evidence_storage_service),
) -> RefundRecord:
    """Accept multipart file upload, validate, store, and append evidence metadata."""
    record = repo.get_refund_request(refund_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found",
        )

    raw_content_type = request.headers.get("content-type", "")
    content_type_lower = raw_content_type.lower()
    if "multipart/form-data" not in content_type_lower:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request content-type must be multipart/form-data.",
        )
    body = await request.body()
    _, uploaded_files = _parse_multipart_request(raw_content_type, body)
    if not uploaded_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file uploaded in multipart request.",
        )
    file = uploaded_files[0]

    filename = file.filename or "evidence_file"
    ext = Path(filename).suffix.lower()
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    if ext not in allowed_extensions:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "urn:problem:bad-request",
                "title": "Bad Request",
                "status": status.HTTP_400_BAD_REQUEST,
                "detail": f"Disallowed file extension '{ext}'. Allowed extensions are: {sorted(allowed_extensions)}",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    content_type = file.content_type or ""
    file_bytes = await file.read()

    try:
        storage_service.validate_file(file_bytes=file_bytes, content_type=content_type)
    except ValueError as e:
        msg = str(e)
        if "exceeds maximum allowed limit" in msg:
            return JSONResponse(
                status_code=HTTP_413_STATUS,
                content={
                    "type": "urn:problem:payload-too-large",
                    "title": "Payload Too Large",
                    "status": HTTP_413_STATUS,
                    "detail": msg,
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "urn:problem:bad-request",
                "title": "Bad Request",
                "status": status.HTTP_400_BAD_REQUEST,
                "detail": msg,
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    saved_meta = storage_service.save_file(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        refund_id=refund_id,
        order_id=record.order_id,
    )

    updated = repo.add_evidence(
        refund_id=refund_id,
        evidence_item=saved_meta,
    )

    if record.status == "awaiting_clarification":
        response_text = f"Uploaded evidence file: {filename}"
        updated = repo.submit_clarification_response(
            refund_id=refund_id,
            clarification_response=response_text,
        )
        background_tasks.add_task(
            resume_refund_workflow,
            refund_id=record.refund_id,
            response_text=response_text,
            evidence=[saved_meta],
            repository=repo,
        )

    return updated


CLARIFY_REQUEST_OPENAPI_EXTRA: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "response_text": {
                            "type": "string",
                            "description": "Customer clarification response text.",
                        }
                    },
                    "required": ["response_text"],
                }
            },
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "response_text": {
                            "type": "string",
                            "description": "Customer clarification response text.",
                        },
                        "evidence_file": {
                            "type": "string",
                            "format": "binary",
                            "description": "Optional supporting evidence image file.",
                        },
                    },
                    "required": ["response_text"],
                }
            },
        },
    }
}


@router.post(
    "/{refund_id}/clarify",
    response_model=RefundRecord,
    status_code=status.HTTP_200_OK,
    summary="Submit customer clarification response and resume evaluation",
    openapi_extra=CLARIFY_REQUEST_OPENAPI_EXTRA,
)
async def clarify_refund_request(
    refund_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    repo: RefundRepository = Depends(get_repository),
    storage_service: EvidenceStorageService = Depends(get_evidence_storage_service),
) -> RefundRecord:
    """Submit customer clarification response to resume paused evaluation."""
    raw_content_type = request.headers.get("content-type", "")
    content_type_lower = raw_content_type.lower()
    response_text: str | None = None
    evidence_file: UploadFile | None = None

    if "multipart/form-data" in content_type_lower:
        body = await request.body()
        form_fields, form_files = _parse_multipart_request(raw_content_type, body)
        raw_text = form_fields.get("response_text")
        if raw_text is None or not str(raw_text).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'response_text' cannot be blank or empty.",
            )
        response_text = str(raw_text).strip()
        if form_files:
            evidence_file = form_files[0]
    elif "application/x-www-form-urlencoded" in content_type_lower:
        from urllib.parse import parse_qs
        body = await request.body()
        parsed = parse_qs(body.decode("utf-8", errors="replace"))
        raw_text_list = parsed.get("response_text", [])
        raw_text = raw_text_list[0] if raw_text_list else None
        if raw_text is None or not str(raw_text).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'response_text' cannot be blank or empty.",
            )
        response_text = str(raw_text).strip()
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Invalid or missing request body.",
            )
        try:
            payload = RefundClarificationRequest.model_validate(body)
            response_text = payload.response_text
        except Exception as err:
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail=str(err),
            )

    record = repo.get_refund_request(refund_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found",
        )
    if record.status != "awaiting_clarification":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Refund request '{refund_id}' is not awaiting clarification (current status: '{record.status}')",
        )

    if evidence_file is not None:
        filename = evidence_file.filename or "evidence_file"
        ext = Path(filename).suffix.lower()
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        if ext not in allowed_extensions:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "type": "urn:problem:bad-request",
                    "title": "Bad Request",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "detail": f"Disallowed file extension '{ext}'. Allowed extensions are: {sorted(allowed_extensions)}",
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )
        file_bytes = await evidence_file.read()
        file_content_type = evidence_file.content_type or ""
        try:
            storage_service.validate_file(file_bytes=file_bytes, content_type=file_content_type)
        except ValueError as e:
            msg = str(e)
            if "exceeds maximum allowed limit" in msg:
                return JSONResponse(
                    status_code=HTTP_413_STATUS,
                    content={
                        "type": "urn:problem:payload-too-large",
                        "title": "Payload Too Large",
                        "status": HTTP_413_STATUS,
                        "detail": msg,
                        "instance": request.url.path,
                    },
                    media_type="application/problem+json",
                )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "type": "urn:problem:bad-request",
                    "title": "Bad Request",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "detail": msg,
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )
        saved_meta = storage_service.save_file(
            file_bytes=file_bytes,
            filename=filename,
            content_type=file_content_type,
            refund_id=refund_id,
            order_id=record.order_id,
        )
        repo.add_evidence(refund_id=refund_id, evidence_item=saved_meta)

    updated = repo.submit_clarification_response(
        refund_id=refund_id,
        clarification_response=response_text,
    )
    await broadcaster.publish(
        "refund_update",
        {
            "refund_id": refund_id,
            "order_id": record.order_id,
            "status": updated.status,
        },
    )
    background_tasks.add_task(
        resume_refund_workflow,
        refund_id=record.refund_id,
        response_text=response_text,
        repository=repo,
    )
    return updated


@router.post(
    "/{refund_id}/request-proof",
    response_model=RefundRecord,
    status_code=status.HTTP_200_OK,
    summary="Submit reviewer proof request for an escalated refund",
)
async def request_reviewer_proof_endpoint(
    refund_id: str,
    payload: ReviewerProofRequest,
    repo: RefundRepository = Depends(get_repository),
) -> RefundRecord:
    """Accept reviewer proof request for an escalated refund, generate customer notification email, and transition to awaiting_clarification."""
    record = repo.get_refund_request(refund_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found.",
        )
    if record.status != "escalated":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Refund request '{refund_id}' is not in 'escalated' status (current status: '{record.status}').",
        )

    email_text = generate_reviewer_proof_email(
        order_id=record.order_id,
        proof_prompt=payload.proof_prompt,
        customer_name=payload.customer_name,
        refund_id=refund_id,
    )
    try:
        updated = repo.request_reviewer_proof(
            refund_id=refund_id,
            proof_prompt=payload.proof_prompt,
            notification_email_text=email_text,
        )
    except RefundNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found.",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    await broadcaster.publish(
        "refund_update",
        {
            "refund_id": refund_id,
            "order_id": record.order_id,
            "status": updated.status,
        },
    )
    return updated


