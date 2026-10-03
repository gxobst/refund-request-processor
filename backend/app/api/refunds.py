import asyncio
import csv
from datetime import datetime, timedelta, timezone
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
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from app.agents.proof_notifier import generate_reviewer_proof_email
from app.auth.rbac import (
    get_approval_limit_for_role,
    get_current_user_identity,
    get_current_user_role,
    require_supervisor_role,
)
from app.db.repository import RefundNotFoundError, RefundRepository
from app.graph.runner import resume_refund_workflow, run_refund_workflow
from app.schemas.order import ORDER_ID_PATTERN
from app.services.broadcaster import broadcaster
from app.core.config import get_settings
from app.services.email_delivery import send_export_report_email
from app.schemas.refund import (
    BulkExportJobRequest,
    BulkExportJobResponse,
    EvidenceItem,
    ExportScheduleCreate,
    ExportScheduleResponse,
    ExportScheduleUpdate,
    ExportTriggerResponse,
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
    role: str = Depends(get_current_user_role),
    repo: RefundRepository = Depends(get_repository),
) -> RefundRecord:
    """Apply a human operator decision override to a refund request."""
    valid_roles = ("agent", "supervisor", "senior_manager")
    if role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "urn:problem:forbidden",
                "title": "Forbidden",
                "status": status.HTTP_403_FORBIDDEN,
                "detail": "Authorized operator role required to perform manual overrides.",
                "instance": request.url.path,
            },
        )

    operator_id = get_current_user_identity(request)
    record = repo.get_refund_request(refund_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund request '{refund_id}' not found",
        )

    dec_lower = payload.override_decision.strip().lower()

    if dec_lower in ("approve", "approved"):
        amount = record.refund_amount
        if amount is None:
            amount = record.order_amount
        if amount is None:
            from app.graph.nodes import _lookup_order_data

            order_data = _lookup_order_data(record.order_id)
            if order_data and "order_amount" in order_data:
                try:
                    amount = float(order_data["order_amount"])
                except (ValueError, TypeError):
                    amount = 0.0
            else:
                amount = 0.0

        limit = get_approval_limit_for_role(role)
        if amount > limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "type": "urn:problem:forbidden",
                    "title": "Forbidden",
                    "status": status.HTTP_403_FORBIDDEN,
                    "detail": f"Refund amount ${amount:.2f} exceeds your {role} approval limit of ${limit:.2f}. Escalation to senior approval required.",
                    "instance": request.url.path,
                },
            )

    escalation_tier = "senior_manager" if dec_lower in ("escalate", "escalated") else None

    try:
        try:
            updated = repo.apply_override(
                refund_id=refund_id,
                override_decision=payload.override_decision,
                override_reason=payload.reason,
                overridden_by=operator_id,
                escalation_tier=escalation_tier,
            )
        except TypeError:
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
            "escalation_tier": updated.escalation_tier,
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


EXPORT_COLUMNS_DEFINITION: list[tuple[str, str]] = [
    ("refund_id", "Refund ID"),
    ("order_id", "Order ID"),
    ("status", "Status"),
    ("decision", "Decision"),
    ("category", "Category"),
    ("refund_amount", "Refund Amount"),
    ("confidence_score", "Confidence Score"),
    ("customer_request_text", "Customer Request"),
    ("reasoning", "Decision Reasoning"),
    ("override_decision", "Override Decision"),
    ("override_reason", "Override Reason"),
    ("created_at", "Created At"),
    ("updated_at", "Updated At"),
]

CSV_EXPORT_HEADERS = [header for _, header in EXPORT_COLUMNS_DEFINITION]

COLUMN_DISPLAY_NAMES: dict[str, str] = {
    col_id: header for col_id, header in EXPORT_COLUMNS_DEFINITION
}

# Mapping for case-insensitive / normalized lookup by either ID or Display Header
COLUMN_LOOKUP_MAP: dict[str, str] = {}
for _col_id, _header in EXPORT_COLUMNS_DEFINITION:
    COLUMN_LOOKUP_MAP[_col_id.lower()] = _col_id
    COLUMN_LOOKUP_MAP[_col_id.lower().replace("_", " ")] = _col_id
    COLUMN_LOOKUP_MAP[_col_id.lower().replace("_", "-")] = _col_id
    COLUMN_LOOKUP_MAP[_header.lower()] = _col_id
    COLUMN_LOOKUP_MAP[_header.lower().replace(" ", "_")] = _col_id
    COLUMN_LOOKUP_MAP[_header.lower().replace(" ", "-")] = _col_id

COLUMN_LOOKUP_MAP["customer_request"] = "customer_request_text"
COLUMN_LOOKUP_MAP["customer request"] = "customer_request_text"
COLUMN_LOOKUP_MAP["customer-request"] = "customer_request_text"
COLUMN_LOOKUP_MAP["decision_reasoning"] = "reasoning"
COLUMN_LOOKUP_MAP["decision reasoning"] = "reasoning"
COLUMN_LOOKUP_MAP["decision-reasoning"] = "reasoning"


def _resolve_single_column(name: str) -> str | None:
    norm = name.strip().lower()
    return COLUMN_LOOKUP_MAP.get(norm)


def _get_column_value(r: Any, col_id: str) -> str:
    rec_dict = r.model_dump() if hasattr(r, "model_dump") else (r if isinstance(r, dict) else getattr(r, "__dict__", {}))
    if col_id == "refund_id":
        return str(rec_dict.get("refund_id") or getattr(r, "refund_id", "") or "")
    elif col_id == "order_id":
        return str(rec_dict.get("order_id") or getattr(r, "order_id", "") or "")
    elif col_id == "status":
        return str(rec_dict.get("status") or getattr(r, "status", "") or "")
    elif col_id == "decision":
        val = rec_dict.get("decision")
        if val is None:
            val = getattr(r, "decision", None)
        return "" if val is None else str(val)
    elif col_id == "category":
        val = rec_dict.get("category")
        if val is None:
            val = getattr(r, "category", None)
        return "" if val is None else str(val)
    elif col_id == "refund_amount":
        amt = rec_dict.get("refund_amount")
        if amt is None:
            amt = rec_dict.get("order_amount")
        return "" if amt is None else str(amt)
    elif col_id == "confidence_score":
        conf = rec_dict.get("confidence_score")
        if conf is None and hasattr(r, "confidence_score"):
            conf = getattr(r, "confidence_score")
        return "" if conf is None else str(conf)
    elif col_id == "customer_request_text":
        return str(rec_dict.get("customer_request_text") or getattr(r, "customer_request_text", "") or "")
    elif col_id == "reasoning":
        val = rec_dict.get("reasoning")
        if val is None:
            val = getattr(r, "reasoning", None)
        return "" if val is None else str(val)
    elif col_id == "override_decision":
        val = rec_dict.get("override_decision")
        if val is None:
            val = getattr(r, "override_decision", None)
        return "" if val is None else str(val)
    elif col_id == "override_reason":
        val = rec_dict.get("override_reason")
        if val is None:
            val = getattr(r, "override_reason", None)
        return "" if val is None else str(val)
    elif col_id == "created_at":
        return str(rec_dict.get("created_at") or getattr(r, "created_at", "") or "")
    elif col_id == "updated_at":
        return str(rec_dict.get("updated_at") or getattr(r, "updated_at", "") or "")
    return ""


def _get_json_column_value(r: Any, col_id: str) -> Any:
    rec_dict = r.model_dump(mode="json") if hasattr(r, "model_dump") else (r if isinstance(r, dict) else getattr(r, "__dict__", {}))
    if col_id == "refund_amount":
        amt = rec_dict.get("refund_amount")
        if amt is None:
            amt = rec_dict.get("order_amount")
        return amt
    return rec_dict.get(col_id)


def _format_export_csv(records: list[RefundRecord], columns: list[str] | None = None) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)

    if columns is not None:
        resolved_cols: list[str] = []
        for c in columns:
            res = _resolve_single_column(c)
            resolved_cols.append(res if res is not None else c)
        headers = [COLUMN_DISPLAY_NAMES.get(cid, cid) for cid in resolved_cols]
    else:
        resolved_cols = [c[0] for c in EXPORT_COLUMNS_DEFINITION]
        headers = CSV_EXPORT_HEADERS

    writer.writerow(headers)

    for r in records:
        writer.writerow([_get_column_value(r, col_id) for col_id in resolved_cols])

    return output.getvalue()


def _parse_and_validate_columns(
    columns: list[str] | None,
    request: Request | None = None,
) -> tuple[list[str] | None, JSONResponse | None]:
    """Parse and validate column identifiers/header names, returning resolved column IDs or RFC 9457 ProblemDetails."""
    if columns is None:
        if request and "columns" in request.query_params:
            return None, JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "type": "urn:problem:bad-request",
                    "title": "Bad Request",
                    "status": 400,
                    "detail": "At least one column must be selected",
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )
        return None, None

    # Flatten and strip comma-delimited strings and lists
    raw_items: list[str] = []
    for item in columns:
        if not item:
            continue
        for part in item.split(","):
            p = part.strip()
            if p:
                raw_items.append(p)

    if not raw_items:
        return None, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "urn:problem:bad-request",
                "title": "Bad Request",
                "status": 400,
                "detail": "At least one column must be selected",
                "instance": request.url.path if request else "",
            },
            media_type="application/problem+json",
        )

    resolved: list[str] = []
    invalid: list[str] = []
    for item in raw_items:
        col_id = _resolve_single_column(item)
        if col_id is None:
            invalid.append(item)
        else:
            resolved.append(col_id)

    if invalid:
        return None, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "urn:problem:bad-request",
                "title": "Bad Request",
                "status": 400,
                "detail": f"Invalid column(s): {', '.join(invalid)}",
                "instance": request.url.path if request else "",
            },
            media_type="application/problem+json",
        )

    return resolved, None


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export refund queue records as CSV or JSON",
)
async def export_refund_requests(
    request: Request,
    format: str = Query(default="csv"),
    status: RefundStatus | None = Query(default=None),
    columns: list[str] | None = Query(default=None),
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

    resolved_cols, err_resp = _parse_and_validate_columns(columns, request=request)
    if err_resp:
        return err_resp

    records = repo.list_refund_requests(status=status, limit=10000)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    status_str = status.strip().lower() if status else "all"

    if normalized_format == "csv":
        filename = f"refunds-{status_str}-{timestamp}.csv"
        csv_content = _format_export_csv(records, columns=resolved_cols)
        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        filename = f"refunds-{status_str}-{timestamp}.json"
        if resolved_cols is not None:
            json_data = [
                {col_id: _get_json_column_value(r, col_id) for col_id in resolved_cols}
                for r in records
            ]
        else:
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


# In-memory export job store
_export_jobs: dict[str, dict[str, Any]] = {}


def reset_export_jobs() -> None:
    """Reset the in-memory export job store (used for test isolation)."""
    _export_jobs.clear()


def get_export_jobs() -> dict[str, dict[str, Any]]:
    """Return reference to in-memory export jobs."""
    return _export_jobs


def _parse_filter_date(val: str, is_end_date: bool = False) -> datetime:
    """Parse ISO-8601 or YYYY-MM-DD date filter string into timezone-aware UTC datetime."""
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if is_end_date and len(val.strip()) == 10:  # YYYY-MM-DD format
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


async def process_export_job(
    job_id: str,
    request_data: BulkExportJobRequest,
    repo: RefundRepository,
    storage: EvidenceStorageService,
) -> None:
    """Background export task worker processing bulk refund queries and persistence."""
    if job_id not in _export_jobs:
        return
    _export_jobs[job_id]["status"] = "processing"

    try:
        # Fetch records from repository
        records = repo.list_refund_requests(status=request_data.status, limit=100000)

        # Apply date filters if provided
        start_dt = None
        if request_data.start_date:
            start_dt = _parse_filter_date(request_data.start_date, is_end_date=False)

        end_dt = None
        if request_data.end_date:
            end_dt = _parse_filter_date(request_data.end_date, is_end_date=True)

        if start_dt is not None or end_dt is not None:
            filtered_records = []
            for r in records:
                r_created = getattr(r, "created_at", None)
                if not r_created:
                    continue
                try:
                    iso_s = r_created.strip()
                    if iso_s.endswith("Z"):
                        iso_s = iso_s[:-1] + "+00:00"
                    rec_dt = datetime.fromisoformat(iso_s)
                    if rec_dt.tzinfo is None:
                        rec_dt = rec_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                if start_dt is not None and rec_dt < start_dt:
                    continue
                if end_dt is not None and rec_dt > end_dt:
                    continue
                filtered_records.append(r)
            records = filtered_records

        # Ensure status filtering is strict
        if request_data.status is not None:
            status_lower = request_data.status.strip().lower()
            records = [r for r in records if getattr(r, "status", "").lower() == status_lower]

        # Serialize to CSV or JSON
        if request_data.format == "csv":
            content_str = _format_export_csv(records, columns=request_data.columns)
            payload_bytes = content_str.encode("utf-8")
        else:
            if request_data.columns is not None:
                resolved_cols: list[str] = []
                for c in request_data.columns:
                    res = _resolve_single_column(c)
                    resolved_cols.append(res if res is not None else c)
                json_data = [
                    {col_id: _get_json_column_value(r, col_id) for col_id in resolved_cols}
                    for r in records
                ]
            else:
                json_data = [
                    r.model_dump(mode="json") if hasattr(r, "model_dump") else r
                    for r in records
                ]
            content_str = json.dumps(json_data, indent=2)
            payload_bytes = content_str.encode("utf-8")

        # Save export artifact to S3 or local filesystem
        download_url = storage.save_export_file(
            file_bytes=payload_bytes,
            job_id=job_id,
            format=request_data.format,
        )

        _export_jobs[job_id]["status"] = "completed"
        _export_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _export_jobs[job_id]["record_count"] = len(records)
        _export_jobs[job_id]["download_url"] = download_url
    except Exception as e:
        _export_jobs[job_id]["status"] = "failed"
        _export_jobs[job_id]["error"] = str(e)
        _export_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


@router.post(
    "/export/jobs",
    response_model=BulkExportJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create asynchronous bulk queue export job",
)
async def create_bulk_export_job(
    request: Request,
    body: BulkExportJobRequest,
    background_tasks: BackgroundTasks,
    repo: RefundRepository = Depends(get_repository),
    storage: EvidenceStorageService = Depends(get_evidence_storage_service),
) -> Any:
    """Create a new asynchronous bulk queue export job."""
    if body.columns is not None:
        resolved_cols, err_resp = _parse_and_validate_columns(body.columns, request=request)
        if err_resp:
            return err_resp
        body.columns = resolved_cols

    s_dt = None
    e_dt = None
    if body.start_date:
        try:
            s_dt = _parse_filter_date(body.start_date, is_end_date=False)
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "type": "urn:problem:bad-request",
                    "title": "Bad Request",
                    "status": 400,
                    "detail": f"Invalid start_date '{body.start_date}': {e}",
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )
    if body.end_date:
        try:
            e_dt = _parse_filter_date(body.end_date, is_end_date=True)
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "type": "urn:problem:bad-request",
                    "title": "Bad Request",
                    "status": 400,
                    "detail": f"Invalid end_date '{body.end_date}': {e}",
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )

    if s_dt is not None and e_dt is not None and s_dt > e_dt:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "urn:problem:bad-request",
                "title": "Bad Request",
                "status": 400,
                "detail": f"start_date '{body.start_date}' cannot be after end_date '{body.end_date}'.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    job_id = f"exp_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    expires_at = (now + timedelta(seconds=3600)).isoformat()

    job_data: dict[str, Any] = {
        "job_id": job_id,
        "status": "pending",
        "format": body.format,
        "created_at": created_at,
        "expires_at": expires_at,
        "completed_at": None,
        "download_url": None,
        "record_count": None,
        "error": None,
        "status_filter": body.status,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "columns": body.columns,
    }
    _export_jobs[job_id] = job_data

    background_tasks.add_task(process_export_job, job_id, body, repo, storage)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=BulkExportJobResponse(**job_data).model_dump(mode="json"),
    )


@router.get(
    "/export/jobs/{job_id}/download",
    status_code=status.HTTP_200_OK,
    summary="Download bulk export file",
)
async def download_bulk_export(
    job_id: str,
    request: Request,
    storage: EvidenceStorageService = Depends(get_evidence_storage_service),
) -> Response:
    """Download the generated export file from local filesystem or redirect to S3."""
    if job_id not in _export_jobs:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export job '{job_id}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    job = _export_jobs[job_id]
    if job.get("status") != "completed":
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export job '{job_id}' has not completed yet.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    download_url = job.get("download_url") or ""
    if download_url.startswith("http://") or download_url.startswith("https://"):
        return RedirectResponse(url=download_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    try:
        content = storage.get_export_file(job_id=job_id, format=job["format"])
    except FileNotFoundError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export file for job '{job_id}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    filename = f"refunds-export-{job_id}.{job['format']}"
    media_type = "text/csv; charset=utf-8" if job["format"] == "csv" else "application/json"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/export/jobs/{job_id}",
    response_model=BulkExportJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get bulk export job status",
)
async def get_bulk_export_job(
    job_id: str,
    request: Request,
) -> Any:
    """Retrieve status, metadata, and download URL for an export job."""
    if job_id not in _export_jobs:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export job '{job_id}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    return BulkExportJobResponse(**_export_jobs[job_id])


# In-memory export schedule store
_export_schedules: dict[str, dict[str, Any]] = {}


def reset_export_schedules() -> None:
    """Reset the in-memory export schedule store (used for test isolation)."""
    _export_schedules.clear()


def get_export_schedules_store() -> dict[str, dict[str, Any]]:
    """Return reference to in-memory export schedule store."""
    return _export_schedules


@router.post(
    "/export/schedules",
    response_model=ExportScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recurring queue export schedule",
)
async def create_export_schedule(
    body: ExportScheduleCreate,
    request: Request,
) -> Any:
    """Create a new automated recurring export schedule."""
    resolved_cols: list[str] | None = None
    if body.columns is not None:
        resolved_cols, err_resp = _parse_and_validate_columns(body.columns, request=request)
        if err_resp:
            return err_resp

    schedule_id = f"sch_{uuid.uuid4().hex[:10]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    schedule_data: dict[str, Any] = {
        "schedule_id": schedule_id,
        "name": body.name,
        "recipients": body.recipients,
        "frequency": body.frequency,
        "format": body.format,
        "status_filter": body.status_filter,
        "columns": resolved_cols if resolved_cols is not None else body.columns,
        "enabled": body.enabled,
        "created_at": now_iso,
        "last_run": None,
        "last_status": "never_run",
    }
    _export_schedules[schedule_id] = schedule_data
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ExportScheduleResponse(**schedule_data).model_dump(mode="json"),
    )


@router.get(
    "/export/schedules",
    response_model=list[ExportScheduleResponse],
    status_code=status.HTTP_200_OK,
    summary="List all recurring queue export schedules",
)
async def list_export_schedules() -> Any:
    """List all configured export schedules."""
    return [ExportScheduleResponse(**s) for s in _export_schedules.values()]


@router.get(
    "/export/schedules/{schedule_id}",
    response_model=ExportScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get export schedule details",
)
async def get_export_schedule(
    schedule_id: str,
    request: Request,
) -> Any:
    """Retrieve details for a specific export schedule."""
    if schedule_id not in _export_schedules:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export schedule '{schedule_id}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )
    return ExportScheduleResponse(**_export_schedules[schedule_id])


@router.put(
    "/export/schedules/{schedule_id}",
    response_model=ExportScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing export schedule",
)
async def update_export_schedule(
    schedule_id: str,
    body: ExportScheduleUpdate,
    request: Request,
) -> Any:
    """Update configuration fields on an existing export schedule."""
    if schedule_id not in _export_schedules:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export schedule '{schedule_id}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    resolved_cols: list[str] | None = None
    if body.columns is not None:
        resolved_cols, err_resp = _parse_and_validate_columns(body.columns, request=request)
        if err_resp:
            return err_resp

    schedule = _export_schedules[schedule_id]
    if body.name is not None:
        schedule["name"] = body.name
    if body.recipients is not None:
        schedule["recipients"] = body.recipients
    if body.frequency is not None:
        schedule["frequency"] = body.frequency
    if body.format is not None:
        schedule["format"] = body.format
    if "status_filter" in body.model_fields_set:
        schedule["status_filter"] = body.status_filter
    if "columns" in body.model_fields_set:
        schedule["columns"] = resolved_cols if resolved_cols is not None else body.columns
    if body.enabled is not None:
        schedule["enabled"] = body.enabled

    return ExportScheduleResponse(**schedule)


@router.delete(
    "/export/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an export schedule",
)
async def delete_export_schedule(
    schedule_id: str,
    request: Request,
) -> Response:
    """Delete an existing export schedule."""
    if schedule_id not in _export_schedules:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export schedule '{schedule_id}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )
    del _export_schedules[schedule_id]
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/export/schedules/{schedule_id}/trigger",
    response_model=ExportTriggerResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually trigger an export schedule run and email delivery",
)
async def trigger_export_schedule(
    schedule_id: str,
    request: Request,
    repo: RefundRepository = Depends(get_repository),
) -> Any:
    """Manually trigger immediate execution and email delivery for an export schedule."""
    if schedule_id not in _export_schedules:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export schedule '{schedule_id}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    schedule = _export_schedules[schedule_id]
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        status_filter = schedule.get("status_filter")
        records = repo.list_refund_requests(status=status_filter, limit=10000)

        fmt = schedule.get("format", "csv")
        cols = schedule.get("columns")

        if fmt == "csv":
            content_str = _format_export_csv(records, columns=cols)
            payload_bytes = content_str.encode("utf-8")
            ext = "csv"
            mime_type = "text/csv"
        else:
            if cols is not None:
                json_data = [
                    {col_id: _get_json_column_value(r, col_id) for col_id in cols}
                    for r in records
                ]
            else:
                json_data = [
                    r.model_dump(mode="json") if hasattr(r, "model_dump") else r
                    for r in records
                ]
            content_str = json.dumps(json_data, indent=2)
            payload_bytes = content_str.encode("utf-8")
            ext = "json"
            mime_type = "application/json"

        settings = get_settings()
        sender = settings.ses_sender_email
        filename = f"refunds-export-{schedule_id}.{ext}"
        subject = f"Refund Queue Export Report: {schedule['name']}"
        body_text = (
            f"Scheduled refund queue export report for '{schedule['name']}'.\n\n"
            f"Frequency: {schedule.get('frequency')}\n"
            f"Status filter: {status_filter or 'All'}\n"
            f"Total records exported: {len(records)}\n"
            f"Generated at: {now_iso}\n"
        )
        body_html = (
            f"<h2>Refund Queue Export Report</h2>"
            f"<p>Scheduled export report for <strong>{schedule['name']}</strong>.</p>"
            f"<ul>"
            f"<li><strong>Frequency:</strong> {schedule.get('frequency')}</li>"
            f"<li><strong>Status Filter:</strong> {status_filter or 'All'}</li>"
            f"<li><strong>Total Records:</strong> {len(records)}</li>"
            f"<li><strong>Generated At:</strong> {now_iso}</li>"
            f"</ul>"
        )

        send_export_report_email(
            sender=sender,
            recipients=schedule["recipients"],
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachment_filename=filename,
            attachment_bytes=payload_bytes,
            attachment_mime_type=mime_type,
            settings=settings,
        )

        schedule["last_run"] = now_iso
        schedule["last_status"] = "success"

        return ExportTriggerResponse(
            schedule_id=schedule_id,
            records_exported=len(records),
            recipients_delivered=schedule["recipients"],
            status="success",
            executed_at=now_iso,
        )
    except Exception as e:
        schedule["last_run"] = now_iso
        schedule["last_status"] = "failure"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "type": "urn:problem:internal-server-error",
                "title": "Internal Server Error",
                "status": 500,
                "detail": f"Failed to execute export schedule '{schedule_id}': {e}",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
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


