"""Unit tests for Classifier Agent and classification output schemas."""

from unittest.mock import MagicMock
from langchain_core.runnables import RunnableLambda
import pytest

from app.agents.classifier import classify_refund_request, classifier_node
from app.schemas.classifier import ClassificationOutput


def make_mock_llm(output: ClassificationOutput) -> MagicMock:
    """Helper creating a mocked BaseChatModel returning structured output."""
    mock = MagicMock()
    mock.with_structured_output.return_value = RunnableLambda(lambda _: output)
    return mock


@pytest.mark.parametrize(
    "category",
    ["damaged", "wrong_item", "changed_mind", "late_delivery", "missing_item"],
)
def test_classify_all_five_categories(category: str):
    # Arrange
    expected_output = ClassificationOutput(
        category=category,  # type: ignore[arg-type]
        confidence_score=0.95,
        reasoning=f"Request clearly describes a {category} scenario.",
    )
    mock_llm = make_mock_llm(expected_output)

    # Act
    result = classify_refund_request("Customer request text...", llm=mock_llm)

    # Assert
    assert result.category == category
    assert result.confidence_score == 0.95
    assert result.is_low_confidence is False
    assert result.reasoning == f"Request clearly describes a {category} scenario."


@pytest.mark.parametrize(
    ("score", "expected_low_confidence"),
    [
        (0.0, True),
        (0.5, True),
        (0.69, True),
        (0.70, False),
        (0.85, False),
        (1.0, False),
    ],
)
def test_classification_is_low_confidence_threshold(
    score: float, expected_low_confidence: bool
):
    # Arrange & Act
    output = ClassificationOutput(
        category="damaged",
        confidence_score=score,
        reasoning="Test reasoning.",
    )

    # Assert
    assert output.is_low_confidence is expected_low_confidence


def test_classify_handles_empty_or_whitespace_text():
    # Arrange & Act: no LLM needed for empty text
    empty_result = classify_refund_request("")
    whitespace_result = classify_refund_request("   \n\t  ")

    # Assert
    assert empty_result.confidence_score == 0.0
    assert empty_result.is_low_confidence is True
    assert "Empty" in empty_result.reasoning

    assert whitespace_result.confidence_score == 0.0
    assert whitespace_result.is_low_confidence is True


def test_classifier_node_contract():
    # Arrange
    expected_output = ClassificationOutput(
        category="wrong_item",
        confidence_score=0.88,
        reasoning="Customer ordered blue shoes but received red ones.",
    )
    mock_llm = make_mock_llm(expected_output)

    state = {
        "refund_id": "ref_12345",
        "order_id": "ORD-1002",
        "customer_request_text": "I ordered blue sneakers but received red boots instead.",
    }

    # Monkeypatch get_bedrock_llm inside classifier module
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act
        node_result = classifier_node(state)

    # Assert
    assert node_result["category"] == "wrong_item"
    assert node_result["confidence_score"] == 0.88
    assert node_result["classification_confidence"] == 0.88
    assert node_result["classification_reasoning"] == "Customer ordered blue shoes but received red ones."
    assert node_result["is_low_confidence"] is False


def test_classifier_node_with_low_confidence():
    # Arrange
    low_conf_output = ClassificationOutput(
        category="damaged",
        confidence_score=0.45,
        reasoning="Vague complaint about product condition.",
    )
    mock_llm = make_mock_llm(low_conf_output)

    state = {"customer_request_text": "Something is not right with my package."}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)
        node_result = classifier_node(state)

    # Assert
    assert node_result["is_low_confidence"] is True
    assert node_result["confidence_score"] == 0.45
