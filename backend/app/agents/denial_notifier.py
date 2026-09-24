"""Denial Notifier module for generating empathetic, transparent customer denial notification emails."""

from typing import Any


def generate_denial_email(
    order_id: str,
    refund_id: str | None = None,
    customer_name: str | None = None,
    failed_rules: list[str] | None = None,
    policy_reasoning: str | None = None,
    category: str | None = None,
) -> str:
    """Construct an empathetic, professional customer denial notification email explaining policy failure reasons.

    Args:
        order_id: The order identifier.
        refund_id: Optional refund request identifier.
        customer_name: Optional customer name for greeting.
        failed_rules: Optional list of failed rule names (e.g. ['refund_window_days']).
        policy_reasoning: Optional policy checker reasoning or operator override reason.
        category: Optional refund category (e.g. 'damaged').

    Returns:
        Formatted customer denial email text (strictly omitting any RMA or return instructions).
    """
    greeting = f"Dear {customer_name}," if customer_name else "Dear Customer,"

    explanations: list[str] = []
    rules = failed_rules or []

    if "refund_window_days" in rules:
        explanations.append(
            "- Return Window Expired: The request was submitted after our allowed return window had elapsed. "
            "Under our return policy, refund requests must be initiated within the designated return period from purchase or delivery."
        )

    if "eligible_delivery_statuses" in rules:
        explanations.append(
            "- Ineligible Delivery Status: The current delivery status of your order does not meet our refund eligibility criteria."
        )

    # Check for visual damage verification failure
    is_damage_verification_failure = (
        "physical_damage_verification" in rules
        or "damage_verification" in rules
        or (
            category == "damaged"
            and policy_reasoning
            and any(
                phrase in policy_reasoning.lower()
                for phrase in ("no damage detected", "intact", "blurry", "unverified damage", "not damaged")
            )
        )
    )
    if is_damage_verification_failure:
        explanations.append(
            "- Damage Verification: Our visual inspection of the provided evidence did not identify visible physical damage on the ordered item consistent with the reported claim."
        )

    if not explanations:
        if policy_reasoning and policy_reasoning.strip():
            explanations.append(f"- Policy Requirement: {policy_reasoning.strip()}")
        else:
            explanations.append(
                "- Policy Requirement: The order does not meet our standard policy eligibility requirements."
            )

    reasons_block = "\n".join(explanations)

    email_text = f"""{greeting}

Thank you for contacting us regarding your refund request for order {order_id}. After a thorough review of your order and our store return guidelines, we regret to inform you that we are unable to approve your refund request at this time.

Reason for Determination:
{reasons_block}

If you have additional information, photographs, or questions regarding this determination, please feel free to reach out to our Customer Support Team. We are here to help and address any concerns you may have.

Sincerely,
Customer Support Team"""
    return email_text
