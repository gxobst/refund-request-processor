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


CLARIFICATION_SYSTEM_PROMPT = """You are a courteous e-commerce customer support specialist evaluating refund requests.
When a customer's refund request is ambiguous, lacks critical details, or requires supporting evidence, craft a clear, polite follow-up question asking for specific missing details (such as photos of damaged items, packaging condition, delivery details, or verification of affected items).
Identify the missing aspects and explain your reasoning clearly."""

CLARIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", CLARIFICATION_SYSTEM_PROMPT),
    (
        "human",
        """Customer Request: {customer_request_text}
Category: {category}
Order Details: {order}

Please generate a polite follow-up clarification question, identify missing aspects, and provide your reasoning:""",
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
            clarification_prompt="Could you please provide more details about the issue with your order and specify which items are affected?",
            missing_aspects=["issue_description", "item_details"],
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
