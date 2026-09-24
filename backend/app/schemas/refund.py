"""Refund request schemas and data models."""

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

RefundStatus = Literal["pending", "completed", "escalated", "awaiting_clarification"]
RefundDecision = Literal["auto_approve", "deny", "escalate"]


class RefundCreateRequest(BaseModel):
    """Request payload for submitting a new refund request."""

    order_id: str = Field(..., min_length=1, description="Associated order identifier.")
    customer_request_text: str = Field(
        ..., min_length=1, description="Customer refund explanation."
    )

    @field_validator("order_id", "customer_request_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be blank or empty.")
        return v.strip()


class RefundCreateResponse(BaseModel):
    """Response payload returned upon accepting a refund submission."""

    refund_id: str
    order_id: str
    status: str = "pending"
    created_at: str


class RefundRecord(BaseModel):
    """Complete refund request record as stored in DynamoDB."""

    refund_id: str = Field(..., description="Unique identifier for the refund request.")
    order_id: str = Field(..., description="ID of the associated order.")
    customer_request_text: str = Field(..., description="Customer refund explanation.")
    status: RefundStatus = Field(default="pending", description="Current status of the request.")
    decision: str | None = Field(default=None, description="Automated or manual refund decision.")
    reasoning: str | None = Field(default=None, description="Explanation for the decision.")
    matched_policy_rule: dict[str, Any] | None = Field(
        default=None, description="Policy rule evaluated against the order."
    )
    confidence_score: float | None = Field(
        default=None, description="Model confidence score for the classification/decision."
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 creation timestamp.",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 last updated timestamp.",
    )
    override_decision: str | None = Field(
        default=None, description="Decision provided by a human operator override."
    )
    override_reason: str | None = Field(
        default=None, description="Explanation provided for the manual override."
    )
    overridden_at: str | None = Field(
        default=None, description="ISO-8601 timestamp when override was applied."
    )
    clarification_prompt: str | None = Field(
        default=None, description="Question asked to customer for request clarification."
    )
    clarification_response: str | None = Field(
        default=None, description="Customer-provided clarification response."
    )
    clarification_count: int = Field(
        default=0, ge=0, description="Number of clarification cycles attempted."
    )
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Audit log of external tool invocations, arguments, and results.",
    )
    approval_email_text: str | None = Field(
        default=None,
        description="Confirmation and return instructions email text generated for approved refunds.",
    )


class RefundDecisionUpdate(BaseModel):
    """Payload for updating agent decision on a refund request."""

    decision: RefundDecision
    reasoning: str
    matched_policy_rule: dict[str, Any] | None = None
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    status: RefundStatus
    tool_calls: list[dict[str, Any]] | None = None
    approval_email_text: str | None = None


class RefundOverrideUpdate(BaseModel):
    """Payload for recording a human operator override."""

    override_decision: str
    override_reason: str = Field(..., min_length=1)


OverrideDecisionType = Literal["approve", "deny"]


class RefundOverrideRequest(BaseModel):
    """Request payload for submitting a human operator override."""

    override_decision: OverrideDecisionType = Field(
        ..., description="Manual override decision ('approve' or 'deny')."
    )
    reason: str = Field(
        ..., min_length=1, description="Operator explanation justifying the override."
    )

    @field_validator("reason")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Reason cannot be blank or whitespace-only.")
        return v.strip()


class RefundClarificationRequest(BaseModel):
    """Request payload for customer submitting clarification."""

    response_text: str = Field(
        ..., min_length=1, description="Customer-provided clarification response text."
    )

    @field_validator("response_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be blank or empty.")
        return v.strip()

