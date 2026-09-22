"""Decision Agent schema definitions."""

from typing import Any, Literal
from pydantic import BaseModel, Field

DecisionType = Literal["auto_approve", "deny", "escalate"]


class DecisionOutput(BaseModel):
    """Final decision output produced by the Decision Agent."""

    decision: DecisionType = Field(
        ...,
        description="Final refund decision: 'auto_approve', 'deny', or 'escalate'.",
    )
    reasoning: str = Field(
        ...,
        description="Clear explanation justifying the final decision.",
    )
    matched_policy_rule: dict[str, Any] | None = Field(
        default=None,
        description="The policy rule evaluated during the workflow.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score reflecting decision certainty (0.0 to 1.0).",
    )
