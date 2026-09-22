"""FastAPI router for refund request operations, queue listing, and manual overrides."""

from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.db.repository import RefundNotFoundError, RefundRepository
from app.graph.runner import run_refund_workflow
from app.schemas.refund import (
    RefundCreateRequest,
    RefundCreateResponse,
    RefundOverrideRequest,
    RefundRecord,
)

router = APIRouter(prefix="/refunds", tags=["refunds"])


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


@router.post(
    "",
    response_model=RefundCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a refund request for automated evaluation",
)
async def submit_refund_request(
    payload: RefundCreateRequest,
    background_tasks: BackgroundTasks,
    repo: RefundRepository = Depends(get_repository),
) -> RefundCreateResponse:
    """Accept and initiate asynchronous multi-agent processing for a refund request."""
    # 1. Create initial pending record in DynamoDB
    record = repo.create_refund_request(
        order_id=payload.order_id,
        customer_request_text=payload.customer_request_text,
    )

    # 2. Schedule async LangGraph workflow execution in the background
    background_tasks.add_task(
        run_refund_workflow,
        refund_id=record.refund_id,
        order_id=record.order_id,
        customer_request_text=record.customer_request_text,
        repository=repo,
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

