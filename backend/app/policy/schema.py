"""Refund policy schema definitions and validation models."""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class RefundCategory(str, Enum):
    """Supported refund categories."""

    DAMAGED = "damaged"
    WRONG_ITEM = "wrong_item"
    CHANGED_MIND = "changed_mind"
    LATE_DELIVERY = "late_delivery"
    MISSING_ITEM = "missing_item"


RefundCategoryLiteral = Literal[
    "damaged",
    "wrong_item",
    "changed_mind",
    "late_delivery",
    "missing_item",
]


class CategoryPolicy(BaseModel):
    """Policy rules governing refund eligibility for a specific category."""

    refund_window_days: int = Field(
        ...,
        gt=0,
        description="Number of days following delivery/purchase within which refunds are allowed.",
    )
    eligible_delivery_statuses: list[str] = Field(
        ...,
        min_length=1,
        description="List of order delivery statuses eligible for refund under this category.",
    )
    max_order_amount: float = Field(
        ...,
        ge=0.0,
        description="Maximum order amount eligible for refund under this category.",
    )


class PolicyConfig(BaseModel):
    """Complete refund policy configuration mapping each category to its policy rules."""

    damaged: CategoryPolicy
    wrong_item: CategoryPolicy
    changed_mind: CategoryPolicy
    late_delivery: CategoryPolicy
    missing_item: CategoryPolicy

    def __getitem__(self, item: str | RefundCategory) -> CategoryPolicy:
        key = item.value if isinstance(item, RefundCategory) else str(item)
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(item)

    def get(self, item: str | RefundCategory, default: Any = None) -> Any:
        key = item.value if isinstance(item, RefundCategory) else str(item)
        return getattr(self, key, default)


PolicyEvaluationStatus = Literal["pass", "fail", "ambiguous"]


class PolicyEvaluationResult(BaseModel):
    """Result of deterministic policy evaluation."""

    status: Literal["pass", "fail", "ambiguous"]
    passed_rules: list[str] = Field(default_factory=list)
    failed_rules: list[str] = Field(default_factory=list)
    details: str | dict[str, str] = ""
    matched_policy_rule: CategoryPolicy | dict[str, Any] | None = None

