"""Analytics metrics schemas and data models."""

from pydantic import BaseModel, Field


class StatusBreakdown(BaseModel):
    """Breakdown of refund requests by current processing status."""

    pending: int = Field(default=0, ge=0, description="Requests currently pending evaluation.")
    completed: int = Field(default=0, ge=0, description="Requests successfully evaluated or finalized.")
    escalated: int = Field(default=0, ge=0, description="Requests escalated for human/supervisor review.")
    awaiting_clarification: int = Field(
        default=0, ge=0, description="Requests awaiting customer clarification or evidence."
    )


class DecisionBreakdown(BaseModel):
    """Breakdown of refund requests by decision outcome."""

    auto_approve: int = Field(default=0, ge=0, description="Requests automatically approved.")
    deny: int = Field(default=0, ge=0, description="Requests denied based on policy rules.")
    escalate: int = Field(default=0, ge=0, description="Requests escalated for human intervention.")
    pending: int = Field(default=0, ge=0, description="Requests with decision unfinalized or pending.")


class AnalyticsMetricsResponse(BaseModel):
    """Aggregate operational analytics and AI performance metrics."""

    total_requests: int = Field(default=0, ge=0, description="Total count of refund requests.")
    status_breakdown: StatusBreakdown = Field(
        default_factory=StatusBreakdown, description="Counts of requests by status."
    )
    decision_breakdown: DecisionBreakdown = Field(
        default_factory=DecisionBreakdown, description="Counts of requests by decision outcome."
    )
    auto_approval_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Proportion of total requests auto-approved (0.0 - 1.0)."
    )
    override_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Proportion of completed requests with supervisor overrides (0.0 - 1.0).",
    )
    average_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Arithmetic mean of AI confidence scores (0.0 - 1.0)."
    )
    category_breakdown: dict[str, int] = Field(
        default_factory=dict, description="Counts of requests grouped by product/reason category."
    )
