"""Policy Checker schemas and models."""

from typing import Any, Literal
from pydantic import BaseModel, Field

from app.policy.schema import CategoryPolicy

PolicyStatusType = Literal["pass", "fail", "ambiguous"]


class PolicyCheckerOutput(BaseModel):
    """Structured output from the Policy Checker Agent."""

    policy_status: PolicyStatusType = Field(
        ...,
        description="Policy outcome status: 'pass', 'fail', or 'ambiguous'.",
    )
    matched_policy_rule: dict[str, Any] | CategoryPolicy | None = Field(
        default=None,
        description="Policy rule evaluated against the order.",
    )
    passed_rules: list[str] = Field(
        default_factory=list,
        description="List of policy rules that were satisfied.",
    )
    failed_rules: list[str] = Field(
        default_factory=list,
        description="List of policy rules that failed.",
    )
    policy_reasoning: str = Field(
        ...,
        description="Detailed explanation justifying the policy evaluation outcome.",
    )
