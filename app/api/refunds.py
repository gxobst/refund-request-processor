"""FastAPI router for refund request operations."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.db.repository import RefundRepository
from app.graph.runner import run_refund_workflow
from app.schemas.refund import (
    RefundCreateRequest,
    RefundCreateResponse,
    RefundRecord,
)

router = APIRouter(prefix="/refunds", tags=["refunds"])


def get_repository() -> RefundRepository:
    """Dependency provider for RefundRepository."""
    return RefundRepository()


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
