"""Clarification Generator Agent module for crafting customer follow-up prompts."""

from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.agents.llm import get_bedrock_llm


class ClarificationOutput(BaseModel):
    """Structured output schema for clarification follow-up questions."""

    clarification_prompt: str = Field(
        ...,
        description="The follow-up question directed to the customer requesting missing details or photos.",
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="List of specific information, evidence, or documents needed from the customer.",
    )
    reasoning: str = Field(
        ...,
        description="Justification explaining why clarification is required before policy evaluation.",
    )


FALLBACK_CLARIFICATION_EMAIL = """Dear Customer,

Thank you for reaching out to us regarding your refund request.

We are currently unable to process your claim because your message was blank or did not provide sufficient details. Could you please reply with a specific explanation of the issue you experienced and specify which items from your order are affected?

If your claim involves broken or damaged merchandise, please also provide clear photo proof of both the damaged item and the exterior shipping box/packaging condition.

Thank you for your cooperation and understanding.

Sincerely,
Customer Support Team"""

CLARIFICATION_SYSTEM_PROMPT = """You are a courteous e-commerce customer support specialist evaluating refund requests.
When a customer's refund request is ambiguous, lacks critical details, or requires supporting evidence, compose a complete, polite customer email in the 'clarification_prompt' field featuring:
1. Formal Greeting: Address the customer courteously (e.g., 'Dear Customer,').
2. Statement of Missing Information: Clearly state what details are currently missing or unclear in their request.
3. Specific Questions: Ask clear, targeted questions to gather the exact information needed to process the refund.
4. Mandatory Damage Evidence Rule: Whenever a claim involves physical damage, defects, or broken goods (or category is 'damaged'), you MUST explicitly mandate that the customer provide clear photo proof showing BOTH:
   - The damaged or defective item clearly displaying the damage.
   - The shipping box/exterior packaging condition upon delivery.
   For non-damage claims (such as wrong item, missing item, or changed mind), ask for the specific missing reason or details without falsely demanding damage photos.
5. Product Mismatch Inquiries: When a product mismatch is detected between the customer's request and the purchased item recorded in the order details, compose a polite customer email asking the customer to clarify whether they are claiming a refund for the ordered item (referencing the ordered product name explicitly) or if they may have entered an incorrect order number.
6. Professional Sign-off: Conclude with a warm, professional closing (e.g., 'Sincerely,\\nCustomer Support Team').

Populate 'missing_aspects' with a list of specific information, evidence, or documents needed from the customer (e.g., ['photo_proof_of_damage', 'packaging_condition_proof'] for damage claims, or ['product_confirmation', 'order_number_verification'] for product mismatches).
Populate 'reasoning' with a concise justification explaining why clarification is required before policy evaluation.
"""

CLARIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", CLARIFICATION_SYSTEM_PROMPT),
    (
        "human",
        """Customer Request: {customer_request_text}
Category: {category}
Order Details: {order}{product_mismatch_context}

Please compose a complete, polite customer clarification email, identify missing aspects, and provide your reasoning:""",
    ),
])


def generate_clarification_prompt(
    customer_request_text: str,
    category: str | None = None,
    order: dict[str, Any] | None = None,
    llm: BaseChatModel | None = None,
    is_product_mismatch: bool = False,
    mismatch_reason: str | None = None,
) -> ClarificationOutput:
    """Generate a polite clarification follow-up question for low-confidence, ambiguous, or product-mismatch requests.

    Args:
        customer_request_text: Customer explanation text.
        category: Refund category if classified, otherwise None.
        order: Order details dictionary if available, otherwise None.
        llm: Optional LangChain BaseChatModel instance. Defaults to get_bedrock_llm().
        is_product_mismatch: Whether an explicit product discrepancy was detected.
        mismatch_reason: Optional details describing the product mismatch.

    Returns:
        ClarificationOutput instance with prompt, missing aspects, and reasoning.
    """
    if not customer_request_text or not customer_request_text.strip():
        return ClarificationOutput(
            clarification_prompt=FALLBACK_CLARIFICATION_EMAIL,
            missing_aspects=["issue_description", "item_details", "damage_and_packaging_proof"],
            reasoning="Empty or whitespace-only customer request text.",
        )

    order_id = (order.get("order_id") if order else "") or ""
    ordered_item = (
        order.get("item")
        or order.get("item_title")
        or order.get("product_name")
        or ""
    ) if order else ""
    if not ordered_item and order_id:
        from app.agents.policy_checker import ORDER_ID_TO_ITEM
        ordered_item = ORDER_ID_TO_ITEM.get(order_id, "the purchased item")
    if not ordered_item:
        ordered_item = "the item recorded on your order"

    if is_product_mismatch and llm is None:
        order_str = f" for order {order_id}" if order_id else ""
        prompt = (
            f"Dear Customer,\n\n"
            f"Thank you for contacting us regarding your refund request{order_str}.\n\n"
            f"We noticed that your refund request references a different product than {ordered_item}, which is recorded for this order. "
            f"Could you please clarify whether you are requesting a refund for {ordered_item}, or if you may have entered an incorrect order number?\n\n"
            f"Sincerely,\nCustomer Support Team"
        )
        return ClarificationOutput(
            clarification_prompt=prompt,
            missing_aspects=["product_confirmation", "order_number_verification"],
            reasoning=f"Customer request describes conflicting item; clarification needed regarding ordered item ({ordered_item}).",
        )

    mismatch_context = ""
    if is_product_mismatch:
        order_str = f" for order {order_id}" if order_id else ""
        reason_str = f" (Issue detected: {mismatch_reason})" if mismatch_reason else ""
        mismatch_context = (
            f"\n\n[PRODUCT MISMATCH DETECTED]: The customer's request describes a different item than the ordered item "
            f"('{ordered_item}'{order_str}).{reason_str} Compose a polite customer email explicitly mentioning '{ordered_item}' "
            f"and asking the customer to clarify whether they are claiming a refund for {ordered_item} or entered an incorrect order number."
        )

    model = llm or get_bedrock_llm()
    structured_model = model.with_structured_output(ClarificationOutput)
    chain = CLARIFICATION_PROMPT | structured_model

    result = chain.invoke({
        "customer_request_text": customer_request_text.strip(),
        "category": category or "unclassified",
        "order": str(order) if order is not None else "None",
        "product_mismatch_context": mismatch_context,
    })

    if isinstance(result, dict):
        return ClarificationOutput.model_validate(result)
    return result
