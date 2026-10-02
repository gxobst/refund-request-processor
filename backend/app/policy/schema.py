"""Refund policy schema definitions and validation models."""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


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

    return_window_days: int = Field(
        ...,
        gt=0,
        description="Number of days following delivery/purchase within which refunds are allowed.",
    )
    refund_window_days: int = Field(
        ...,
        gt=0,
        description="Alias for return_window_days.",
    )
    eligible_delivery_statuses: list[str] = Field(
        ...,
        min_length=1,
        description="List of order delivery statuses eligible for refund under this category.",
    )
    max_refund_amount: float = Field(
        ...,
        ge=0.0,
        description="Maximum order or refund amount eligible under this category.",
    )
    max_order_amount: float = Field(
        ...,
        ge=0.0,
        description="Alias for max_refund_amount.",
    )
    auto_approve_threshold: float = Field(
        default=0.0,
        ge=0.0,
        description="Maximum refund amount threshold for automated zero-touch approval.",
    )
    requires_proof: bool = Field(
        default=False,
        description="Whether customer photo evidence is required for refunds under this category.",
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "return_window_days" in data and "refund_window_days" not in data:
                data["refund_window_days"] = data["return_window_days"]
            elif "refund_window_days" in data and "return_window_days" not in data:
                data["return_window_days"] = data["refund_window_days"]

            if "max_refund_amount" in data and "max_order_amount" not in data:
                data["max_order_amount"] = data["max_refund_amount"]
            elif "max_order_amount" in data and "max_refund_amount" not in data:
                data["max_refund_amount"] = data["max_order_amount"]

            if "auto_approve_threshold" not in data:
                data["auto_approve_threshold"] = 0.0
            if "requires_proof" not in data:
                data["requires_proof"] = False
        return data

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name == "return_window_days" and getattr(self, "refund_window_days", None) != value:
            super().__setattr__("refund_window_days", value)
        elif name == "refund_window_days" and getattr(self, "return_window_days", None) != value:
            super().__setattr__("return_window_days", value)
        elif name == "max_refund_amount" and getattr(self, "max_order_amount", None) != value:
            super().__setattr__("max_order_amount", value)
        elif name == "max_order_amount" and getattr(self, "max_refund_amount", None) != value:
            super().__setattr__("max_refund_amount", value)


class CategoryPolicyUpdate(BaseModel):
    """Schema for updating category policy thresholds and configuration."""

    return_window_days: int | None = Field(
        default=None,
        gt=0,
        description="Number of days following delivery within which refunds are allowed (must be > 0).",
    )
    refund_window_days: int | None = Field(
        default=None,
        gt=0,
        description="Alias for return_window_days.",
    )
    max_refund_amount: float | None = Field(
        default=None,
        ge=0.0,
        description="Maximum refund amount allowed (must be >= 0.0).",
    )
    max_order_amount: float | None = Field(
        default=None,
        ge=0.0,
        description="Alias for max_refund_amount.",
    )
    auto_approve_threshold: float | None = Field(
        default=None,
        ge=0.0,
        description="Threshold under which refunds can be automatically approved (must be >= 0.0).",
    )
    requires_proof: bool | None = Field(
        default=None,
        description="Whether customer photo evidence is required for refunds.",
    )
    eligible_delivery_statuses: list[str] | None = Field(
        default=None,
        min_length=1,
        description="List of order delivery statuses eligible for refund under this category.",
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_update_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "return_window_days" in data and "refund_window_days" not in data:
                data["refund_window_days"] = data["return_window_days"]
            elif "refund_window_days" in data and "return_window_days" not in data:
                data["return_window_days"] = data["refund_window_days"]

            if "max_refund_amount" in data and "max_order_amount" not in data:
                data["max_order_amount"] = data["max_refund_amount"]
            elif "max_order_amount" in data and "max_refund_amount" not in data:
                data["max_refund_amount"] = data["max_order_amount"]
        return data


class PolicyItemResponse(BaseModel):
    """Response schema for a single category policy configuration item."""

    category: str = Field(..., description="Refund category name.")
    return_window_days: int = Field(..., gt=0, description="Return window in days.")
    max_refund_amount: float = Field(..., ge=0.0, description="Maximum refund amount.")
    auto_approve_threshold: float = Field(default=0.0, ge=0.0, description="Auto-approve threshold.")
    requires_proof: bool = Field(default=False, description="Whether customer photo evidence is required.")
    eligible_delivery_statuses: list[str] = Field(..., min_length=1, description="Eligible delivery statuses.")
    refund_window_days: int | None = Field(default=None, description="Backward-compatible alias for return_window_days.")
    max_order_amount: float | None = Field(default=None, description="Backward-compatible alias for max_refund_amount.")

    @model_validator(mode="before")
    @classmethod
    def _sync_response_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "return_window_days" in data and "refund_window_days" not in data:
                data["refund_window_days"] = data["return_window_days"]
            elif "refund_window_days" in data and "return_window_days" not in data:
                data["return_window_days"] = data["refund_window_days"]

            if "max_refund_amount" in data and "max_order_amount" not in data:
                data["max_order_amount"] = data["max_refund_amount"]
            elif "max_order_amount" in data and "max_refund_amount" not in data:
                data["max_refund_amount"] = data["max_order_amount"]
        return data


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

