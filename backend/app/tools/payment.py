"""Payment gateway lookup tool for verifying Stripe charge transactions, disputes, and refund eligibility."""

from typing import Any
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field, field_validator


class CallableStructuredTool(StructuredTool):
    """StructuredTool subclass enabling direct invocation as a Python callable."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute tool directly with positional or keyword arguments."""
        if args and not kwargs:
            if self.args_schema:
                schema_fields = list(self.args_schema.model_fields.keys())
                if len(schema_fields) == 1:
                    return self.invoke({schema_fields[0]: args[0]})
            return self.invoke(args[0] if isinstance(args[0], dict) else {"input": args[0]})
        return self.invoke(kwargs)


class PaymentLookupInput(BaseModel):
    """Input schema for payment transaction lookup."""

    order_id: str = Field(
        ...,
        min_length=1,
        description="Order identifier to look up Stripe payment status for.",
    )

    @field_validator("order_id")
    @classmethod
    def not_blank(cls, v: str) -> str:
        """Strip surrounding whitespace and ensure order ID is not blank."""
        if not v or not v.strip():
            raise ValueError("order_id cannot be empty or blank")
        return v.strip()


# Mock payment gateway registry mapped to mock orders
MOCK_PAYMENT_REGISTRY: dict[str, dict[str, Any]] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "transaction_id": "ch_3N8xYz1001001",
        "charge_status": "succeeded",
        "payment_method": "credit_card",
        "charge_amount": 149.99,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": True,
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "transaction_id": "ch_3N8xYz1002002",
        "charge_status": "succeeded",
        "payment_method": "credit_card",
        "charge_amount": 45.00,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": True,
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "transaction_id": "ch_3N8xYz1003003",
        "charge_status": "succeeded",
        "payment_method": "credit_card",
        "charge_amount": 350.00,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": True,
    },
    "ORD-1004": {
        "order_id": "ORD-1004",
        "transaction_id": "ch_3N8xYz1004004",
        "charge_status": "succeeded",
        "payment_method": "credit_card",
        "charge_amount": 85.50,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": True,
    },
    "ORD-1005": {
        "order_id": "ORD-1005",
        "transaction_id": "ch_3N8xYz1005005",
        "charge_status": "succeeded",
        "payment_method": "apple_pay",
        "charge_amount": 220.00,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": True,
    },
    "ORD-1006": {
        "order_id": "ORD-1006",
        "transaction_id": "ch_3N8xYz1006006",
        "charge_status": "disputed",
        "payment_method": "credit_card",
        "charge_amount": 45.00,
        "currency": "usd",
        "dispute_status": "under_review",
        "refund_eligibility": False,
    },
    "ORD-1007": {
        "order_id": "ORD-1007",
        "transaction_id": "ch_3N8xYz1007007",
        "charge_status": "succeeded",
        "payment_method": "credit_card",
        "charge_amount": 120.00,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": True,
    },
    "ORD-1008": {
        "order_id": "ORD-1008",
        "transaction_id": "ch_3N8xYz1008008",
        "charge_status": "refunded",
        "payment_method": "credit_card",
        "charge_amount": 99.00,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": False,
    },
    "ORD-1009": {
        "order_id": "ORD-1009",
        "transaction_id": "ch_3N8xYz1009009",
        "charge_status": "failed",
        "payment_method": "credit_card",
        "charge_amount": 60.00,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": False,
    },
}


def _make_invalid_payment_response(order_id: str = "") -> dict[str, Any]:
    """Construct standard invalid response payload for blank or missing order ID."""
    return {
        "found": False,
        "order_id": order_id,
        "error": "Order ID must not be empty or blank.",
        "transaction_id": None,
        "charge_status": "invalid",
        "payment_method": "unknown",
        "charge_amount": 0.0,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": False,
    }


def _handle_payment_validation_error(err: Any) -> dict[str, Any]:
    """Handle LangChain / Pydantic validation error gracefully during tool invocation."""
    input_val = ""
    if hasattr(err, "errors"):
        errors = err.errors()
        if errors and "input" in errors[0]:
            val = errors[0]["input"]
            if isinstance(val, dict):
                input_val = str(val.get("order_id", ""))
            elif val is not None:
                input_val = str(val)
    return _make_invalid_payment_response(input_val)


@tool("query_payment_transaction", args_schema=PaymentLookupInput)
def query_payment_transaction(order_id: str) -> dict[str, Any]:
    """Query payment transaction status, charge amount, dispute status, and refund eligibility.

    Args:
        order_id: Order identifier to inspect Stripe payment transactions for (e.g. 'ORD-1001').

    Returns:
        Structured dictionary containing transaction ID, charge status, dispute state,
        charge amount, and refund eligibility flag.
    """
    if not order_id or not isinstance(order_id, str) or not order_id.strip():
        return _make_invalid_payment_response(str(order_id) if order_id is not None else "")

    clean_order_id = order_id.strip()
    lookup_key = clean_order_id.upper()

    record = MOCK_PAYMENT_REGISTRY.get(lookup_key)
    if record is not None:
        return {
            "found": True,
            "order_id": record["order_id"],
            "transaction_id": record["transaction_id"],
            "charge_status": record["charge_status"],
            "payment_method": record["payment_method"],
            "charge_amount": float(record["charge_amount"]),
            "currency": record.get("currency", "usd"),
            "dispute_status": record["dispute_status"],
            "refund_eligibility": record["refund_eligibility"],
            "error": None,
        }

    return {
        "found": False,
        "order_id": clean_order_id,
        "error": f"Payment transaction for order '{clean_order_id}' not found.",
        "transaction_id": None,
        "charge_status": "not_found",
        "payment_method": "unknown",
        "charge_amount": 0.0,
        "currency": "usd",
        "dispute_status": "none",
        "refund_eligibility": False,
    }


# Ensure tool supports both direct Python call syntax and LangChain Runnable .invoke()
query_payment_transaction.__class__ = CallableStructuredTool
query_payment_transaction.handle_validation_error = _handle_payment_validation_error
