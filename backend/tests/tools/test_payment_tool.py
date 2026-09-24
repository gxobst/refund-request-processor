"""Unit tests for payment transaction lookup tool."""

import json
from typing import Any
import pytest
from pydantic import ValidationError

from app.db.seed import DEFAULT_MOCK_ORDERS_PATH
from app.tools.payment import (
    PaymentLookupInput,
    query_payment_transaction,
)


def test_payment_lookup_input_schema_validation():
    """Verify PaymentLookupInput validates non-blank order IDs and rejects empty/blank inputs."""
    # Arrange & Act: valid input
    model = PaymentLookupInput(order_id="  ORD-1001  ")

    # Assert: stripped whitespace
    assert model.order_id == "ORD-1001"

    # Act & Assert: empty string
    with pytest.raises(ValidationError):
        PaymentLookupInput(order_id="")

    # Act & Assert: whitespace-only string
    with pytest.raises(ValidationError):
        PaymentLookupInput(order_id="   ")


def test_query_payment_transaction_eligible_order():
    """AC 1206: Verify query_payment_transaction returns valid payment record with charge_status=succeeded, correct amount, and refund_eligibility=True."""
    # Arrange
    order_id = "ORD-1001"

    # Act: direct call with keyword argument
    result = query_payment_transaction(order_id=order_id)

    # Assert
    assert result["found"] is True
    assert result["order_id"] == "ORD-1001"
    assert result["transaction_id"] == "ch_3N8xYz1001001"
    assert result["charge_status"] == "succeeded"
    assert result["payment_method"] == "credit_card"
    assert result["charge_amount"] == 250.0
    assert result["currency"] == "usd"
    assert result["dispute_status"] == "none"
    assert result["refund_eligibility"] is True
    assert result["error"] is None


with open(DEFAULT_MOCK_ORDERS_PATH, encoding="utf-8") as f:
    _MOCK_ORDERS_DATA = json.load(f)


@pytest.mark.parametrize(
    "order_data",
    _MOCK_ORDERS_DATA,
    ids=[o["order_id"] for o in _MOCK_ORDERS_DATA],
)
def test_query_payment_transaction_matches_mock_orders(order_data: dict[str, Any]):
    """Verify that calling query_payment_transaction(order_id)['charge_amount'] strictly equals order_amount in mock_orders.json."""
    order_id = order_data["order_id"]
    expected_amount = order_data["order_amount"]
    result = query_payment_transaction(order_id)
    assert result["found"] is True
    assert result["charge_amount"] == expected_amount


def test_query_payment_transaction_ord_1007():
    """Verify querying ORD-1007 returns charge_amount == 200.0, charge_status == 'succeeded', and refund_eligibility is True."""
    result = query_payment_transaction("ORD-1007")
    assert result["found"] is True
    assert result["order_id"] == "ORD-1007"
    assert result["charge_amount"] == 200.0
    assert result["charge_status"] == "succeeded"
    assert result["refund_eligibility"] is True


def test_query_payment_transaction_disputed_order():
    """AC 1207: Verify query_payment_transaction returns refund_eligibility=False and dispute_status=under_review for disputed order."""
    # Arrange
    order_id = "ORD-1006"

    # Act: direct call with positional argument
    result = query_payment_transaction(order_id)

    # Assert
    assert result["found"] is True
    assert result["order_id"] == "ORD-1006"
    assert result["transaction_id"] == "ch_3N8xYz1006006"
    assert result["charge_status"] == "disputed"
    assert result["dispute_status"] == "under_review"
    assert result["refund_eligibility"] is False
    assert result["error"] is None


def test_query_payment_transaction_other_statuses():
    """Verify payment tool accurately returns refunded and failed charge states."""
    # Refunded charge
    res_refunded = query_payment_transaction("ORD-1008")
    assert res_refunded["found"] is True
    assert res_refunded["charge_status"] == "refunded"
    assert res_refunded["refund_eligibility"] is False

    # Failed charge
    res_failed = query_payment_transaction("ORD-1009")
    assert res_failed["found"] is True
    assert res_failed["charge_status"] == "failed"
    assert res_failed["refund_eligibility"] is False


def test_query_payment_transaction_not_found():
    """AC 1208: Verify query_payment_transaction returns structured not-found response for non-existent order ID."""
    # Arrange
    unknown_order = "ORD-9999"

    # Act
    result = query_payment_transaction(order_id=unknown_order)

    # Assert
    assert result["found"] is False
    assert result["order_id"] == unknown_order
    assert result["error"] == f"Payment transaction for order '{unknown_order}' not found."
    assert result["transaction_id"] is None
    assert result["charge_status"] == "not_found"
    assert result["payment_method"] == "unknown"
    assert result["charge_amount"] == 0.0
    assert result["currency"] == "usd"
    assert result["dispute_status"] == "none"
    assert result["refund_eligibility"] is False


def test_query_payment_transaction_whitespace_and_case_insensitivity():
    """AC 1209: Verify query_payment_transaction strips surrounding whitespace and performs case-insensitive lookup."""
    # Arrange
    raw_input = "  ord-1001  "

    # Act
    result = query_payment_transaction(raw_input)

    # Assert
    assert result["found"] is True
    assert result["order_id"] == "ORD-1001"
    assert result["charge_status"] == "succeeded"
    assert result["refund_eligibility"] is True


def test_query_payment_transaction_empty_and_whitespace_handling():
    """AC 1210: Verify query_payment_transaction handles empty or whitespace-only strings without raising exceptions."""
    # Act: empty string
    empty_res = query_payment_transaction("")
    assert empty_res["found"] is False
    assert empty_res["order_id"] == ""
    assert empty_res["error"] == "Order ID must not be empty or blank."
    assert empty_res["transaction_id"] is None
    assert empty_res["charge_status"] == "invalid"
    assert empty_res["payment_method"] == "unknown"
    assert empty_res["charge_amount"] == 0.0
    assert empty_res["currency"] == "usd"
    assert empty_res["dispute_status"] == "none"
    assert empty_res["refund_eligibility"] is False

    # Act: whitespace string
    ws_res = query_payment_transaction("   ")
    assert ws_res["found"] is False
    assert ws_res["order_id"] == "   "
    assert ws_res["error"] == "Order ID must not be empty or blank."
    assert ws_res["charge_status"] == "invalid"


def test_query_payment_transaction_langchain_metadata_and_invoke():
    """AC 1211: Verify LangChain tool metadata and invocation via query_payment_transaction.invoke."""
    # Metadata assertion
    assert query_payment_transaction.name == "query_payment_transaction"
    assert "payment" in query_payment_transaction.description.lower()
    assert query_payment_transaction.args_schema == PaymentLookupInput

    # Act: invoke with dictionary
    invoke_res = query_payment_transaction.invoke({"order_id": "ORD-1001"})
    assert invoke_res["found"] is True
    assert invoke_res["order_id"] == "ORD-1001"
    assert invoke_res["charge_status"] == "succeeded"

    # Act: invoke with empty string handled gracefully via handle_validation_error
    invoke_empty = query_payment_transaction.invoke({"order_id": ""})
    assert invoke_empty["found"] is False
    assert invoke_empty["charge_status"] == "invalid"
    assert invoke_empty["error"] == "Order ID must not be empty or blank."

    # Act: invoke with whitespace string handled gracefully
    invoke_ws = query_payment_transaction.invoke({"order_id": "   "})
    assert invoke_ws["found"] is False
    assert invoke_ws["charge_status"] == "invalid"
    assert invoke_ws["error"] == "Order ID must not be empty or blank."
