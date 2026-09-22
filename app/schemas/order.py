"""Mock order data schema and validation models."""

from datetime import date
from pydantic import BaseModel, Field, field_validator


class MockOrder(BaseModel):
    """Schema model representing an e-commerce mock order."""

    order_id: str = Field(..., min_length=1, description="Unique identifier for the order.")
    item: str = Field(..., min_length=1, description="Description or name of the ordered item.")
    purchase_date: date = Field(..., description="Date on which the order was placed.")
    order_amount: float = Field(..., gt=0.0, description="Total order monetary value (must be > 0).")
    delivery_date: date | None = Field(
        default=None,
        description="Date on which the order was delivered (None if in transit or cancelled).",
    )
    delivery_status: str = Field(
        ...,
        min_length=1,
        description="Delivery status (e.g., delivered, in_transit, cancelled, pending).",
    )

    @field_validator("delivery_status")
    @classmethod
    def validate_delivery_status(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not cleaned:
            raise ValueError("delivery_status must not be empty or blank")
        return cleaned
