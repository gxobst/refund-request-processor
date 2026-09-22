"""Classifier schema definitions."""

from typing import Literal
from pydantic import BaseModel, Field, computed_field

RefundCategoryType = Literal[
    "damaged",
    "wrong_item",
    "changed_mind",
    "late_delivery",
    "missing_item",
]


class ClassificationOutput(BaseModel):
    """Structured output for refund reason classification."""

    category: RefundCategoryType = Field(
        ...,
        description="Classified refund reason category.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0.",
    )
    reasoning: str = Field(
        ...,
        description="Concise explanation justifying the classification.",
    )

    @computed_field
    @property
    def is_low_confidence(self) -> bool:
        """Indicates whether classification confidence is below the threshold (< 0.7)."""
        return self.confidence_score < 0.7
