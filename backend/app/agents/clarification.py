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
5. Professional Sign-off: Conclude with a warm, professional closing (e.g., 'Sincerely,\\nCustomer Support Team').

Populate 'missing_aspects' with a list of specific information, evidence, or documents needed from the customer (e.g., ['photo_proof_of_damage', 'packaging_condition_proof'] for damage claims).
Populate 'reasoning' with a concise justification explaining why clarification is required before policy evaluation.
"""

CLARIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", CLARIFICATION_SYSTEM_PROMPT),
    (
        "human",
        """Customer Request: {customer_request_text}
Category: {category}
Order Details: {order}

Please compose a complete, polite customer clarification email, identify missing aspects, and provide your reasoning:""",
    ),
])


def generate_clarification_prompt(
    customer_request_text: str,
    category: str | None = None,
    order: dict[str, Any] | None = None,
    llm: BaseChatModel | None = None,
) -> ClarificationOutput:
    """Generate a polite clarification follow-up question for low-confidence or ambiguous requests.

    Args:
        customer_request_text: Customer explanation text.
        category: Refund category if classified, otherwise None.
        order: Order details dictionary if available, otherwise None.
        llm: Optional LangChain BaseChatModel instance. Defaults to get_bedrock_llm().

    Returns:
        ClarificationOutput instance with prompt, missing aspects, and reasoning.
    """
    if not customer_request_text or not customer_request_text.strip():
        return ClarificationOutput(
            clarification_prompt=FALLBACK_CLARIFICATION_EMAIL,
            missing_aspects=["issue_description", "item_details", "damage_and_packaging_proof"],
            reasoning="Empty or whitespace-only customer request text.",
        )

    model = llm or get_bedrock_llm()
    structured_model = model.with_structured_output(ClarificationOutput)
    chain = CLARIFICATION_PROMPT | structured_model

    result = chain.invoke({
        "customer_request_text": customer_request_text.strip(),
        "category": category or "unclassified",
        "order": str(order) if order is not None else "None",
    })

    if isinstance(result, dict):
        return ClarificationOutput.model_validate(result)
    return result
