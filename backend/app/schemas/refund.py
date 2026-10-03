"""Refund request schemas and data models."""

from datetime import datetime, timezone
from typing import Any, Literal
import uuid
from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.order import ORDER_ID_PATTERN

RefundStatus = Literal["pending", "completed", "escalated", "awaiting_clarification"]
RefundDecision = Literal["auto_approve", "deny", "escalate"]


class EvidenceItem(BaseModel):
    """Metadata item representing an uploaded customer proof photo or video."""

    evidence_id: str = Field(
        default_factory=lambda: f"evi_{uuid.uuid4().hex[:8]}",
        description="Unique identifier for the evidence item.",
    )
    storage_key: str = Field(..., description="Unique S3 or local storage key path.")
    filename: str = Field(..., description="Sanitized original file name.")
    content_type: str = Field(..., description="MIME content type (image or video).")
    size_bytes: int = Field(..., ge=0, description="Size of the file in bytes.")
    url: str = Field(..., description="Accessible URL for viewing or downloading the file.")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 creation timestamp.",
    )


class ClarificationTurn(BaseModel):
    """Structured audit log entry representing a single clarification or proof request turn."""

    cycle: int = Field(..., ge=1, description="Clarification cycle number (1-indexed).")
    prompt: str | None = Field(
        default=None,
        description="Clarification or proof prompt sent to the customer.",
    )
    response: str | None = Field(
        default=None,
        description="Customer-provided clarification response.",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp when this clarification turn was initiated.",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="IDs of evidence attachments associated with this clarification turn.",
    )


class RefundCreateRequest(BaseModel):
    """Request payload for submitting a new refund request."""

    order_id: str = Field(
        ...,
        pattern=ORDER_ID_PATTERN,
        description="Associated order identifier.",
    )
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
    overridden_by: str | None = Field(
        default=None,
        description="Identifier or role of the operator who applied the manual override.",
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
    clarification_history: list[ClarificationTurn] = Field(
        default_factory=list,
        description="Structured turn-by-turn audit history of clarification and proof request cycles.",
    )
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Audit log of external tool invocations, arguments, and results.",
    )
    approval_email_text: str | None = Field(
        default=None,
        description="Confirmation and return instructions email text generated for approved refunds.",
    )
    denial_email_text: str | None = Field(
        default=None,
        description="Generated customer notification email text explaining denial reasons.",
    )
    clarification_email_text: str | None = Field(
        default=None,
        description="Generated customer notification email requesting proof or clarification.",
    )
    evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Customer-uploaded proof attachments (images and videos).",
    )
    category: str | None = Field(default=None, description="Classified refund reason category.")


class RefundDecisionUpdate(BaseModel):
    """Payload for updating agent decision on a refund request."""

    decision: RefundDecision
    reasoning: str
    matched_policy_rule: dict[str, Any] | None = None
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    status: RefundStatus
    tool_calls: list[dict[str, Any]] | None = None
    approval_email_text: str | None = None
    denial_email_text: str | None = None
    category: str | None = Field(default=None, description="Classified refund reason category.")


class RefundOverrideUpdate(BaseModel):
    """Payload for recording a human operator override."""

    override_decision: str
    override_reason: str = Field(..., min_length=1)
    denial_email_text: str | None = None
    overridden_by: str | None = Field(
        default=None,
        description="Identifier or role of the operator who applied the manual override.",
    )


OverrideDecisionType = Literal["approve", "deny"]


class RefundOverrideRequest(BaseModel):
    """Request payload for submitting a human operator override."""

    override_decision: OverrideDecisionType = Field(
        ..., description="Manual override decision ('approve' or 'deny')."
    )
    reason: str = Field(
        ..., min_length=1, description="Operator explanation justifying the override."
    )
    override_reason: str | None = Field(
        default=None, description="Alias for operator explanation justifying the override."
    )

    @model_validator(mode="before")
    @classmethod
    def populate_reason_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            val = data.get("override_reason") or data.get("overrideReason") or data.get("reason")
            if val is not None:
                data["reason"] = val
                data["override_reason"] = val
        return data

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


class ReviewerProofRequest(BaseModel):
    """Request payload for reviewer requesting customer proof from escalated status."""

    proof_prompt: str = Field(
        ...,
        min_length=1,
        description="Targeted proof request or inquiry prompt from the reviewer.",
    )
    customer_name: str | None = Field(
        default=None,
        description="Optional customer name for email greeting.",
    )

    @field_validator("proof_prompt")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("proof_prompt cannot be blank or empty.")
        return v.strip()


