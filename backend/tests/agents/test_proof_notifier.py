"""Unit tests for the Proof Notifier module and reviewer proof request email generator."""

import pytest
from app.agents.proof_notifier import generate_reviewer_proof_email


def test_generate_reviewer_proof_email_contents():
    """Verify generate_reviewer_proof_email generates customer email with greeting, prompt, image formats, and upload instructions."""
    order_id = "ORD-1008"
    proof_prompt = "Please provide a clear photo of the cracked screen and the serial number on the back."
    refund_id = "ref-1008-proof"

    email_text = generate_reviewer_proof_email(
        order_id=order_id,
        proof_prompt=proof_prompt,
        refund_id=refund_id,
    )

    # 1. Greeting
    assert "Dear Customer," in email_text
    # 2. Order ID
    assert order_id in email_text
    # 3. Supervisor inquiry prompt
    assert proof_prompt in email_text
    assert "Supervisor Inquiry:" in email_text
    # 4. Allowed image formats (JPEG, PNG, WebP up to 5MB)
    assert "JPEG" in email_text
    assert "PNG" in email_text
    assert "WebP" in email_text
    assert "5MB" in email_text
    # 5. Upload instructions
    assert f"/refunds/{refund_id}/evidence" in email_text
    assert f"/refunds/{refund_id}/clarify" in email_text
    assert "Upload Evidence" in email_text
    # 6. Polite sign-off
    assert "Sincerely," in email_text
    assert "Customer Support Team" in email_text


def test_generate_reviewer_proof_email_with_customer_name():
    """Verify generate_reviewer_proof_email incorporates custom customer name in greeting."""
    order_id = "ORD-1009"
    proof_prompt = "Please upload an image showing the packaging label."
    customer_name = "Jane Doe"

    email_text = generate_reviewer_proof_email(
        order_id=order_id,
        proof_prompt=proof_prompt,
        customer_name=customer_name,
    )

    assert f"Dear {customer_name}," in email_text
    assert order_id in email_text
    assert proof_prompt in email_text
    assert "JPEG" in email_text
    assert "PNG" in email_text
    assert "WebP" in email_text
    assert "5MB" in email_text
