"""Classifier Agent module for customer refund request evaluation."""

from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.agents.llm import get_bedrock_llm
from app.schemas.classifier import ClassificationOutput

CLASSIFIER_SYSTEM_PROMPT = """You are an expert customer support classifier evaluating e-commerce refund requests.
Classify the customer's refund request text into exactly one of the following 5 refund categories:
- 'damaged': The product arrived broken, cracked, defective, crushed, or physically damaged.
- 'wrong_item': The customer received an incorrect item, wrong size, or wrong color than what was ordered.
- 'changed_mind': The customer no longer wants or needs the item, purchased by mistake, or found it elsewhere.
- 'late_delivery': The order arrived after the promised delivery date, or is delayed/still in transit.
- 'missing_item': Part of the order or an item is missing from the delivered package.

Provide a confidence score between 0.0 and 1.0 reflecting how unambiguous the request is.
Provide a concise reasoning explanation justifying your classification.
"""

CLASSIFIER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", CLASSIFIER_SYSTEM_PROMPT),
    ("human", "Customer Refund Request:\n{text}"),
])


def classify_refund_request(
    text: str,
    llm: BaseChatModel | None = None,
) -> ClassificationOutput:
    """Classify customer refund request text using an LLM with structured output.

    Args:
        text: Customer refund request text.
        llm: Optional LangChain BaseChatModel instance. Defaults to get_bedrock_llm().

    Returns:
        ClassificationOutput with category, confidence_score, reasoning, and is_low_confidence.
    """
    if not text or not text.strip():
        return ClassificationOutput(
            category="changed_mind",
            confidence_score=0.0,
            reasoning="Empty or whitespace-only refund request text.",
        )

    model = llm or get_bedrock_llm()
    structured_model = model.with_structured_output(ClassificationOutput)
    chain = CLASSIFIER_PROMPT | structured_model

    result = chain.invoke({"text": text.strip()})

    if isinstance(result, dict):
        return ClassificationOutput.model_validate(result)
    return result


def classifier_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node function executing the Classifier Agent.

    Args:
        state: Workflow state dictionary containing 'customer_request_text'.

    Returns:
        Dictionary containing updated classification keys.
    """
    request_text = state.get("customer_request_text", "")
    output = classify_refund_request(request_text)

    return {
        "category": output.category,
        "confidence_score": output.confidence_score,
        "classification_confidence": output.confidence_score,
        "classification_reasoning": output.reasoning,
        "is_low_confidence": output.is_low_confidence,
    }
