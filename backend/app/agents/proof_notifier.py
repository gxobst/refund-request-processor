"""Proof Notifier module for generating customer notification emails requesting proof or clarification from escalated status."""


def generate_reviewer_proof_email(
    order_id: str,
    proof_prompt: str,
    customer_name: str | None = None,
    refund_id: str | None = None,
) -> str:
    """Construct a professional customer notification email requesting proof or clarification.

    Args:
        order_id: The order identifier.
        proof_prompt: The supervisor inquiry or proof request prompt.
        customer_name: Optional customer name for greeting.
        refund_id: Optional refund request identifier.

    Returns:
        Formatted customer proof request email text containing supervisor inquiry,
        allowed image formats (JPEG, PNG, WebP up to 5MB), and upload/clarification instructions.
    """
    greeting = f"Dear {customer_name}," if customer_name else "Dear Customer,"
    prompt_text = proof_prompt.strip()

    email_text = f"""{greeting}

Thank you for contacting us regarding your refund request for order {order_id}. During our review, our support supervisor requested additional information or photo evidence to proceed with evaluating your request.

Supervisor Inquiry:
{prompt_text}

Evidence Upload & Clarification Instructions:
1. Allowed Formats: We accept clear image files in JPEG, PNG, or WebP format up to 5MB per file.
2. Upload Evidence: You can upload your photo evidence directly via our evidence upload portal or POST /refunds/{refund_id or '<refund_id>'}/evidence.
3. Respond with Details: You can submit your clarification or explanation via POST /refunds/{refund_id or '<refund_id>'}/clarify.

Once your evidence or response is received, our team will promptly resume evaluation of your refund request.

If you have any questions or need further assistance, please contact our support team.

Sincerely,
Customer Support Team"""
    return email_text
