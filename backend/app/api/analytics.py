"""Operational analytics and AI performance metrics API endpoints."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.refunds import get_repository
from app.db.repository import RefundRepository
from app.schemas.analytics import AnalyticsMetricsResponse, AnalyticsTrendsResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/metrics",
    response_model=AnalyticsMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregate operational analytics and AI metrics",
)
def get_analytics_metrics(
    start_date: str | None = Query(None, description="Start date filter (inclusive)."),
    end_date: str | None = Query(None, description="End date filter (inclusive)."),
    repository: RefundRepository = Depends(get_repository),
) -> AnalyticsMetricsResponse:
    """Retrieve operational visibility metrics including decision/status distributions and AI rates."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date",
        )
    return repository.get_analytics_metrics(start_date=start_date, end_date=end_date)


@router.get(
    "/trends",
    response_model=AnalyticsTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get historical trend analytics",
)
def get_analytics_trends(
    start_date: str | None = Query(None, description="Start date filter (inclusive)."),
    end_date: str | None = Query(None, description="End date filter (inclusive)."),
    interval: Literal["daily", "weekly"] = Query("daily", description="Time aggregation interval."),
    repository: RefundRepository = Depends(get_repository),
) -> AnalyticsTrendsResponse:
    """Retrieve historical time-series trends grouped by daily or weekly intervals."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date",
        )
    return repository.get_analytics_trends(
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )
