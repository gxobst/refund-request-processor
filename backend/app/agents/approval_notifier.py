"""Approval Notifier module for generating customer confirmation and product return instructions emails."""

from typing import Any
import uuid


def generate_approval_email(
    order_id: str,
    refund_id: str | None = None,
    customer_name: str | None = None,
    return_window_days: int = 14,
) -> str:
    """Construct complete, professional customer confirmation and product return instructions email text for approved refunds.

    Args:
        order_id: The order identifier.
        refund_id: Optional refund request identifier to trace the RMA.
        customer_name: Optional customer name for greeting.
        return_window_days: Return deadline window in days (default 14).

    Returns:
        Formatted approval confirmation email text.
    """
    greeting = f"Dear {customer_name}," if customer_name else "Dear Customer,"

    clean_order = order_id.replace("ORD-", "").strip() if order_id else "GENERAL"
    if refund_id:
        clean_ref = (
            refund_id.replace("ref-", "")
            .replace("ref_", "")
            .replace("-", "")
            .strip()[:6]
            .upper()
        )
        if not clean_ref:
            clean_ref = uuid.uuid4().hex[:6].upper()
        rma_code = f"RMA-{clean_order}-{clean_ref}"
    else:
        rma_code = f"RMA-{clean_order}-APPROVED"

    email_text = f"""{greeting}

We are pleased to inform you that your refund request for order {order_id} has been approved.

Your Return Merchandise Authorization (RMA) code is: {rma_code}

Return Instructions:
1. Return Window: Please dispatch the item within our explicit {return_window_days}-day return deadline window from the date of this notice.
2. Packaging Instructions: Carefully package the item in its original product packaging or secure protective materials. Ensure all accessories, manuals, and parts are included.
3. Labeling: Please write or affix the RMA code ({rma_code}) clearly on the exterior of the return parcel.

Once our fulfillment center inspects the returned item, your refund will be finalized to your original payment method.

If you have any questions or need further assistance, please contact our support team.

Sincerely,
Customer Support Team"""
    return email_text
