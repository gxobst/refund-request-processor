"""Unit tests for the Approval Notifier agent and approval email generator."""

import pytest
from app.agents.approval_notifier import generate_approval_email


def test_generate_approval_email_contents():
    """Verify that generate_approval_email produces email text with order ID, RMA code, 14-day window, packaging instructions, and polite sign-off."""
    order_id = "ORD-1001"
    refund_id = "ref_1001_approve"

    email_text = generate_approval_email(order_id=order_id, refund_id=refund_id)

    # 1. Greeting
    assert "Dear Customer," in email_text
    # 2. Order ID
    assert order_id in email_text
    # 3. Approval confirmation
    assert "approved" in email_text.lower()
    # 4. RMA code
    assert "RMA" in email_text
    assert "RMA-1001-" in email_text
    # 5. Explicit 14-day return window
    assert "14-day" in email_text
    assert "return deadline window" in email_text
    # 6. Packaging instructions
    assert "Packaging Instructions:" in email_text
    assert "packaging" in email_text.lower()
    assert "accessories" in email_text.lower()
    # 7. Support sign-off
    assert "Sincerely," in email_text
    assert "Customer Support Team" in email_text


def test_generate_approval_email_custom_name_and_window():
    """Verify that customer name and customized return window are incorporated into the generated text."""
    order_id = "ORD-2005"
    refund_id = "ref-2005-vip"

    email_text = generate_approval_email(
        order_id=order_id,
        refund_id=refund_id,
        customer_name="Alice Smith",
        return_window_days=21,
    )

    assert "Dear Alice Smith," in email_text
    assert "ORD-2005" in email_text
    assert "21-day" in email_text
    assert "RMA-2005-" in email_text
    assert "Sincerely," in email_text


def test_generate_approval_email_without_refund_id():
    """Verify that an RMA code and valid email are generated when refund_id is omitted."""
    order_id = "ORD-1010"

    email_text = generate_approval_email(order_id=order_id)

    assert "Dear Customer," in email_text
    assert "ORD-1010" in email_text
    assert "RMA-1010-APPROVED" in email_text
    assert "14-day" in email_text
    assert "Sincerely," in email_text
