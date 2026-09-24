"""Unit tests for Denial Notifier module generating customer denial emails."""

import pytest
from app.agents.denial_notifier import generate_denial_email


def test_generate_denial_email_basic_structure():
    """Verify that generate_denial_email produces email text with formal greeting, order ID, empathetic statement, support options, and professional sign-off."""
    order_id = "ORD-1004"
    refund_id = "ref_1004_deny"

    email_text = generate_denial_email(
        order_id=order_id,
        refund_id=refund_id,
        failed_rules=["refund_window_days"],
    )

    # 1. Formal greeting
    assert "Dear Customer," in email_text
    # 2. Order ID
    assert order_id in email_text
    # 3. Polite statement of decision
    assert "unable to approve your refund request" in email_text
    # 4. Support contact options
    assert "Customer Support Team" in email_text
    assert "reach out" in email_text.lower()
    # 5. Professional sign-off
    assert "Sincerely," in email_text
    assert "Customer Support Team" in email_text


def test_generate_denial_email_custom_customer_name():
    """Verify that custom customer name is included in the greeting."""
    email_text = generate_denial_email(
        order_id="ORD-2001",
        customer_name="John Doe",
        failed_rules=["refund_window_days"],
    )

    assert "Dear John Doe," in email_text
    assert "ORD-2001" in email_text


def test_generate_denial_email_expired_return_window():
    """Verify specific explanation for expired return window (refund_window_days)."""
    email_text = generate_denial_email(
        order_id="ORD-1004",
        failed_rules=["refund_window_days"],
    )

    assert "Return Window Expired:" in email_text
    assert "return period" in email_text.lower() or "return window" in email_text.lower()


def test_generate_denial_email_ineligible_delivery_status():
    """Verify specific explanation for ineligible delivery status (eligible_delivery_statuses)."""
    email_text = generate_denial_email(
        order_id="ORD-1006",
        failed_rules=["eligible_delivery_statuses"],
    )

    assert "Ineligible Delivery Status:" in email_text
    assert "delivery status" in email_text.lower()


def test_generate_denial_email_unverified_damage_or_intact():
    """Verify specific explanation for intact item or unverified damage from visual inspection."""
    email_text = generate_denial_email(
        order_id="ORD-1008",
        category="damaged",
        policy_reasoning="No damage detected. Item appears completely intact.",
    )

    assert "Damage Verification:" in email_text
    assert "visual inspection" in email_text.lower()
    assert "physical damage" in email_text.lower()


def test_generate_denial_email_multiple_failed_rules():
    """Verify that multiple failed rules are each included in the explanation list."""
    email_text = generate_denial_email(
        order_id="ORD-1011",
        failed_rules=["refund_window_days", "eligible_delivery_statuses"],
    )

    assert "Return Window Expired:" in email_text
    assert "Ineligible Delivery Status:" in email_text


def test_generate_denial_email_fallback_reasoning():
    """Verify fallback reasoning when specific rule details are unavailable."""
    email_text = generate_denial_email(
        order_id="ORD-9999",
        policy_reasoning="The submitted receipt does not match platform transaction records.",
    )

    assert "Policy Requirement:" in email_text
    assert "does not match platform transaction records" in email_text


def test_generate_denial_email_strictly_no_rma_or_return_instructions():
    """Verify that denial emails strictly omit RMA codes and return shipping instructions."""
    email_text = generate_denial_email(
        order_id="ORD-1004",
        refund_id="ref-1004",
        customer_name="Bob Builder",
        failed_rules=["refund_window_days"],
    )

    assert "RMA" not in email_text
    assert "Return Merchandise Authorization" not in email_text
    assert "Return Instructions" not in email_text
    assert "dispatch the item" not in email_text
    assert "packaging instructions" not in email_text.lower()
