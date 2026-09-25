from email.parser import BytesParser
from email.policy import default
import io
from pathlib import Path
from typing import Any, Literal
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from starlette.datastructures import UploadFile

from app.db.repository import RefundNotFoundError, RefundRepository
from app.graph.runner import resume_refund_workflow, run_refund_workflow
from app.schemas.refund import (
    EvidenceItem,
    RefundClarificationRequest,
    RefundCreateRequest,
    RefundCreateResponse,
    RefundOverrideRequest,
    RefundRecord,
)
from app.services.storage import EvidenceStorageService, get_evidence_storage_service

router = APIRouter(prefix="/refunds", tags=["refunds"])

HTTP_413_STATUS = 413
HTTP_422_STATUS = 422


def _parse_multipart_request(
    content_type_header: str, body_bytes: bytes
) -> tuple[dict[str, str], list[UploadFile]]:
    """Parse multipart/form-data body using standard library email parser."""
    fields: dict[str, str] = {}
    files: list[UploadFile] = []

    msg_bytes = f"Content-Type: {content_type_header}\r\n\r\n".encode("latin1") + body_bytes
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
    status: Literal["pending", "completed", "escalated"] | None = Query(default=None),
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
    content_type_header = request.headers.get("content-type", "").lower()
    order_id: str | None = None
    customer_request_text: str | None = None
    uploaded_file: UploadFile | None = None

    if "multipart/form-data" in content_type_header:
        body = await request.body()
        form_fields, form_files = _parse_multipart_request(content_type_header, body)
        raw_order_id = form_fields.get("order_id")
        if raw_order_id is None or not str(raw_order_id).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'order_id' cannot be blank or empty.",
            )
        raw_text = form_fields.get("customer_request_text")
        if raw_text is None or not str(raw_text).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'customer_request_text' cannot be blank or empty.",
            )
        order_id = str(raw_order_id).strip()
        customer_request_text = str(raw_text).strip()
        if form_files:
            uploaded_file = form_files[0]
    elif "application/x-www-form-urlencoded" in content_type_header:
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
        raw_text_list = parsed.get("customer_request_text", [])
        raw_text = raw_text_list[0] if raw_text_list else None
        if raw_text is None or not str(raw_text).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'customer_request_text' cannot be blank or empty.",
            )
        order_id = str(raw_order_id).strip()
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Disallowed file extension '{ext}'. Allowed extensions are: {sorted(allowed_extensions)}",
            )
        file_bytes = await uploaded_file.read()
        file_content_type = uploaded_file.content_type or ""
        try:
            storage_service.validate_file(file_bytes=file_bytes, content_type=file_content_type)
        except ValueError as e:
            msg = str(e)
            if "exceeds maximum allowed limit" in msg:
                raise HTTPException(
                    status_code=HTTP_413_STATUS,
                    detail=msg,
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=msg,
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

    # 3. Return accepted response
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
    repo: RefundRepository = Depends(get_repository),
) -> RefundRecord:
    """Apply a human operator decision override to a refund request."""
    try:
        updated = repo.apply_override(
            refund_id=refund_id,
            override_decision=payload.override_decision,
            override_reason=payload.reason,
        )
    except (RefundNotFoundError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found",
        )
    return updated


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

    content_type_header = request.headers.get("content-type", "").lower()
    if "multipart/form-data" not in content_type_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request content-type must be multipart/form-data.",
        )
    body = await request.body()
    _, uploaded_files = _parse_multipart_request(content_type_header, body)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Disallowed file extension '{ext}'. Allowed extensions are: {sorted(allowed_extensions)}",
        )

    content_type = file.content_type or ""
    file_bytes = await file.read()

    try:
        storage_service.validate_file(file_bytes=file_bytes, content_type=content_type)
    except ValueError as e:
        msg = str(e)
        if "exceeds maximum allowed limit" in msg:
            raise HTTPException(
                status_code=HTTP_413_STATUS,
                detail=msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
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
    content_type_header = request.headers.get("content-type", "").lower()
    response_text: str | None = None
    evidence_file: UploadFile | None = None

    if "multipart/form-data" in content_type_header:
        body = await request.body()
        form_fields, form_files = _parse_multipart_request(content_type_header, body)
        raw_text = form_fields.get("response_text")
        if raw_text is None or not str(raw_text).strip():
            raise HTTPException(
                status_code=HTTP_422_STATUS,
                detail="Field 'response_text' cannot be blank or empty.",
            )
        response_text = str(raw_text).strip()
        if form_files:
            evidence_file = form_files[0]
    elif "application/x-www-form-urlencoded" in content_type_header:
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Disallowed file extension '{ext}'. Allowed extensions are: {sorted(allowed_extensions)}",
            )
        file_bytes = await evidence_file.read()
        file_content_type = evidence_file.content_type or ""
        try:
            storage_service.validate_file(file_bytes=file_bytes, content_type=file_content_type)
        except ValueError as e:
            msg = str(e)
            if "exceeds maximum allowed limit" in msg:
                raise HTTPException(
                    status_code=HTTP_413_STATUS,
                    detail=msg,
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=msg,
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
    background_tasks.add_task(
        resume_refund_workflow,
        refund_id=record.refund_id,
        response_text=response_text,
        repository=repo,
    )
    return updated

