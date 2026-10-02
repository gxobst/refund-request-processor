"""Operational analytics and AI performance metrics API endpoints."""

from fastapi import APIRouter, Depends, status

from app.api.refunds import get_repository
from app.db.repository import RefundRepository
from app.schemas.analytics import AnalyticsMetricsResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/metrics",
    response_model=AnalyticsMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregate operational analytics and AI metrics",
)
def get_analytics_metrics(
    repository: RefundRepository = Depends(get_repository),
) -> AnalyticsMetricsResponse:
    """Retrieve operational visibility metrics including decision/status distributions and AI rates."""
    return repository.get_analytics_metrics()
