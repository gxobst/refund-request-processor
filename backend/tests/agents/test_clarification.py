"""Unit tests for the Clarification Generator Agent and graph node."""

from typing import Any
from unittest.mock import MagicMock
from langchain_core.runnables import RunnableLambda
import pytest

from app.agents.clarification import (
    ClarificationOutput,
    generate_clarification_prompt,
)
from app.db.repository import RefundNotFoundError
from app.graph.nodes import clarification_node, set_current_repository


def make_mock_clarification_llm(output: ClarificationOutput | dict[str, Any]) -> MagicMock:
    """Helper creating a mocked BaseChatModel returning structured ClarificationOutput."""
    mock = MagicMock()
    mock.with_structured_output.return_value = RunnableLambda(lambda _: output)
    return mock


def test_generate_clarification_prompt_structured_output():
    # Arrange
    expected_output = ClarificationOutput(
        clarification_prompt="Could you please provide photos of the damaged chair armrest?",
        missing_aspects=["photos_of_damage", "packaging_condition"],
        reasoning="Customer reported damage without photos or description of packaging.",
    )
    mock_llm = make_mock_clarification_llm(expected_output)

    # Act
    result = generate_clarification_prompt(
        customer_request_text="The chair broke when I received it.",
        category="damaged",
        order={"order_id": "ORD-1001", "item": "Office Chair"},
        llm=mock_llm,
    )

    # Assert
    assert isinstance(result, ClarificationOutput)
    assert result.clarification_prompt == "Could you please provide photos of the damaged chair armrest?"
    assert result.missing_aspects == ["photos_of_damage", "packaging_condition"]
    assert "photos" in result.reasoning.lower()


def test_generate_clarification_prompt_structured_output_from_dict():
    # Arrange: LLM returning dict instead of Pydantic model
    dict_output = {
        "clarification_prompt": "Please confirm the serial number and item model.",
        "missing_aspects": ["serial_number"],
        "reasoning": "Missing model identifier.",
    }
    mock_llm = make_mock_clarification_llm(dict_output)

    # Act
    result = generate_clarification_prompt(
        customer_request_text="Need refund for item.",
        llm=mock_llm,
    )

    # Assert
    assert isinstance(result, ClarificationOutput)
    assert result.clarification_prompt == "Please confirm the serial number and item model."
    assert result.missing_aspects == ["serial_number"]


@pytest.mark.parametrize("blank_text", ["", "   ", "\t\n  ", None])
def test_generate_clarification_prompt_fallback_on_blank_text(blank_text: str | None):
    # Arrange: mock LLM should NOT be invoked
    mock_llm = MagicMock()

    # Act
    result = generate_clarification_prompt(
        customer_request_text=blank_text or "",
        llm=mock_llm,
    )

    # Assert
    mock_llm.with_structured_output.assert_not_called()
    assert isinstance(result, ClarificationOutput)
    assert len(result.clarification_prompt) > 0
    assert "details" in result.clarification_prompt.lower()
    assert "issue_description" in result.missing_aspects
    assert "Empty or whitespace-only" in result.reasoning


def test_clarification_node_increments_count_from_0_to_1():
    # Arrange
    state = {
        "refund_id": "ref_clarify_1",
        "customer_request_text": "Broken keyboard.",
        "category": "damaged",
        "clarification_count": 0,
    }
    mock_output = ClarificationOutput(
        clarification_prompt="Please send a picture of the broken keyboard.",
        missing_aspects=["photos"],
        reasoning="Photo evidence required.",
    )
    mock_llm = make_mock_clarification_llm(mock_output)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_llm)

        # Act
        update = clarification_node(state)

    # Assert
    assert update["clarification_count"] == 1
    assert update["status"] == "awaiting_clarification"
    assert update["needs_clarification"] is True
    assert update["clarification_prompt"] == "Please send a picture of the broken keyboard."


def test_clarification_node_increments_count_from_1_to_2():
    # Arrange
    state = {
        "refund_id": "ref_clarify_2",
        "customer_request_text": "Still broken, need replacement.",
        "category": "damaged",
        "clarification_count": 1,
    }
    mock_output = ClarificationOutput(
        clarification_prompt="Could you specify if the package box was damaged upon delivery?",
        missing_aspects=["box_condition"],
        reasoning="Need box details.",
    )
    mock_llm = make_mock_clarification_llm(mock_output)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_llm)

        # Act
        update = clarification_node(state)

    # Assert
    assert update["clarification_count"] == 2
    assert update["status"] == "awaiting_clarification"
    assert update["needs_clarification"] is True
    assert update["clarification_prompt"] == "Could you specify if the package box was damaged upon delivery?"


def test_clarification_node_invokes_repo_request_clarification():
    # Arrange
    mock_repo = MagicMock()
    set_current_repository(mock_repo)
    state = {
        "refund_id": "ref_with_repo_100",
        "customer_request_text": "Item is not working.",
        "category": "damaged",
        "clarification_count": 0,
    }
    mock_output = ClarificationOutput(
        clarification_prompt="Please describe how the item fails to operate.",
        missing_aspects=["failure_symptoms"],
        reasoning="Need details.",
    )
    mock_llm = make_mock_clarification_llm(mock_output)

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_llm)

            # Act
            update = clarification_node(state)

        # Assert
        mock_repo.request_clarification.assert_called_once_with(
            refund_id="ref_with_repo_100",
            clarification_prompt="Please describe how the item fails to operate.",
        )
        assert update["status"] == "awaiting_clarification"
        assert update["clarification_count"] == 1
    finally:
        set_current_repository(None)


def test_clarification_node_executes_cleanly_when_repo_is_none():
    # Arrange: No repo in context
    set_current_repository(None)
    state = {
        "refund_id": "ref_no_repo",
        "customer_request_text": "Item arrived broken.",
        "clarification_count": 0,
    }
    mock_output = ClarificationOutput(
        clarification_prompt="Please upload photos.",
        missing_aspects=["photos"],
        reasoning="Need photos.",
    )
    mock_llm = make_mock_clarification_llm(mock_output)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_llm)

        # Act: should not raise
        update = clarification_node(state)

    # Assert
    assert update["status"] == "awaiting_clarification"
    assert update["clarification_count"] == 1
    assert update["clarification_prompt"] == "Please upload photos."


def test_clarification_node_executes_cleanly_on_refund_not_found():
    # Arrange: repo raises RefundNotFoundError
    mock_repo = MagicMock()
    mock_repo.request_clarification.side_effect = RefundNotFoundError("Not found")
    set_current_repository(mock_repo)

    state = {
        "refund_id": "ref_nonexistent",
        "customer_request_text": "Need help.",
        "clarification_count": 0,
    }
    mock_output = ClarificationOutput(
        clarification_prompt="Please clarify your issue.",
        missing_aspects=["issue"],
        reasoning="Ambiguous.",
    )
    mock_llm = make_mock_clarification_llm(mock_output)

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_llm)

            # Act: should catch exception cleanly
            update = clarification_node(state)

        # Assert
        mock_repo.request_clarification.assert_called_once()
        assert update["status"] == "awaiting_clarification"
        assert update["clarification_count"] == 1
    finally:
        set_current_repository(None)


def test_clarification_node_handles_none_clarification_count():
    # Arrange: state with clarification_count None or missing
    set_current_repository(None)
    state = {
        "customer_request_text": "Unspecified problem.",
    }
    mock_output = ClarificationOutput(
        clarification_prompt="Please describe the issue in detail.",
        missing_aspects=["details"],
        reasoning="Missing info.",
    )
    mock_llm = make_mock_clarification_llm(mock_output)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_llm)

        # Act
        update = clarification_node(state)

    # Assert: defaults 0 -> increments to 1
    assert update["clarification_count"] == 1
    assert update["status"] == "awaiting_clarification"
    assert update["needs_clarification"] is True


def test_clarification_system_prompt_structure_and_rules():
    """Verify that CLARIFICATION_SYSTEM_PROMPT instructs complete customer email and mandatory damage evidence."""
    from app.agents.clarification import CLARIFICATION_SYSTEM_PROMPT

    prompt_lower = CLARIFICATION_SYSTEM_PROMPT.lower()
    assert "formal greeting" in prompt_lower or "greeting" in prompt_lower
    assert "statement of missing information" in prompt_lower or "missing details" in prompt_lower
    assert "specific questions" in prompt_lower
    assert "mandatory damage evidence rule" in prompt_lower or "damage evidence" in prompt_lower
    assert "shipping box" in prompt_lower
    assert "packaging condition" in prompt_lower
    assert "photo proof" in prompt_lower or "image proof" in prompt_lower
    assert "video" not in prompt_lower
    assert "professional sign-off" in prompt_lower or "sign-off" in prompt_lower


def test_generate_clarification_prompt_damage_claim_requires_photo_and_packaging_proof():
    """AC 1875: Verify when category='damaged' or text describes damage, email contains greeting, sign-off, and mandates item & packaging proof."""
    damage_email = (
        "Dear Customer,\n\n"
        "Thank you for contacting support regarding your refund request for order ORD-1010.\n\n"
        "We are sorry to hear that your item arrived damaged. To process your refund under our policy, "
        "we require clear photo proof of both the damaged item and the shipping box/packaging condition upon delivery.\n\n"
        "Could you please also specify if the packaging was torn upon arrival?\n\n"
        "Sincerely,\n"
        "Customer Support Team"
    )
    expected_output = ClarificationOutput(
        clarification_prompt=damage_email,
        missing_aspects=["photo_proof_of_damage", "packaging_condition_proof"],
        reasoning="Physical damage claims require photo proof of both the damaged item and packaging.",
    )
    mock_llm = make_mock_clarification_llm(expected_output)

    result = generate_clarification_prompt(
        customer_request_text="The camera arrived with a cracked lens and crushed box.",
        category="damaged",
        order={"order_id": "ORD-1010", "item": "Professional Mirrorless Camera"},
        llm=mock_llm,
    )

    assert isinstance(result, ClarificationOutput)
    # 1. Email greeting
    assert "dear customer" in result.clarification_prompt.lower()
    # 2. Email sign-off
    assert "sincerely" in result.clarification_prompt.lower() or "customer support" in result.clarification_prompt.lower()
    # 3. Explicit requirement for photo or image proof of both item and packaging (no video)
    assert "photo proof" in result.clarification_prompt.lower() or "image proof" in result.clarification_prompt.lower()
    assert "video" not in result.clarification_prompt.lower()
    assert "damaged item" in result.clarification_prompt.lower()
    assert "packaging" in result.clarification_prompt.lower() or "shipping box" in result.clarification_prompt.lower()
    # 4. Missing aspects includes damage and packaging proof
    assert any("damage" in aspect.lower() for aspect in result.missing_aspects)
    assert any("packaging" in aspect.lower() for aspect in result.missing_aspects)


def test_generate_clarification_prompt_non_damage_claim_does_not_demand_damage_photos():
    """AC 1876: Verify for non-damage claims (e.g. wrong item), email asks for missing details without demanding damage photos."""
    wrong_item_email = (
        "Dear Customer,\n\n"
        "Thank you for reaching out regarding your recent order ORD-1002.\n\n"
        "You mentioned receiving the wrong item. Could you please specify the exact product or model name "
        "you received instead of your ordered headphones, and confirm whether the original tags are attached?\n\n"
        "Sincerely,\n"
        "Customer Support Team"
    )
    expected_output = ClarificationOutput(
        clarification_prompt=wrong_item_email,
        missing_aspects=["received_item_details", "tag_condition"],
        reasoning="Wrong item claim requires description of the incorrect product received.",
    )
    mock_llm = make_mock_clarification_llm(expected_output)

    result = generate_clarification_prompt(
        customer_request_text="I did not get what I ordered, please refund.",
        category="wrong_item",
        order={"order_id": "ORD-1002", "item": "Noise-Cancelling Headphones"},
        llm=mock_llm,
    )

    assert isinstance(result, ClarificationOutput)
    # Greeting and closing present
    assert "dear customer" in result.clarification_prompt.lower()
    assert "sincerely" in result.clarification_prompt.lower()
    # Asks for specific missing details
    assert "wrong item" in result.clarification_prompt.lower() or "received" in result.clarification_prompt.lower()
    # Does NOT demand damage photos
    assert "damage photo" not in result.clarification_prompt.lower()
    assert "damaged item" not in result.clarification_prompt.lower()
    assert not any("damage" in aspect.lower() for aspect in result.missing_aspects)


def test_generate_clarification_prompt_fallback_structured_email_on_blank():
    """AC 1877: Verify empty or whitespace customer text produces fallback email with greeting, details request, and sign-off."""
    mock_llm = MagicMock()

    result = generate_clarification_prompt(customer_request_text="   \n  \t", llm=mock_llm)

    mock_llm.with_structured_output.assert_not_called()
    assert isinstance(result, ClarificationOutput)
    # Formal greeting
    assert "dear customer" in result.clarification_prompt.lower()
    # Request for specific refund reason / details
    assert "specific explanation" in result.clarification_prompt.lower() or "details" in result.clarification_prompt.lower()
    assert "items" in result.clarification_prompt.lower()
    # Evidence instructions
    assert "photo proof" in result.clarification_prompt.lower() or "image proof" in result.clarification_prompt.lower()
    assert "video" not in result.clarification_prompt.lower()
    assert "packaging" in result.clarification_prompt.lower()
    # Professional sign-off
    assert "sincerely" in result.clarification_prompt.lower()
    assert "customer support team" in result.clarification_prompt.lower()


def test_clarification_node_stores_full_email_in_state_and_invokes_repo():
    """AC 1878: Verify clarification_node correctly stores full clarification email text in workflow state and invokes repo."""
    mock_repo = MagicMock()
    set_current_repository(mock_repo)

    clarification_email = (
        "Dear Customer,\n\n"
        "Thank you for contacting customer support. We noticed your request regarding order ORD-1008 lacks detail. "
        "Could you please clarify whether the fitness watch is unresponsive or if parts are missing?\n\n"
        "Sincerely,\n"
        "Customer Support Team"
    )
    expected_output = ClarificationOutput(
        clarification_prompt=clarification_email,
        missing_aspects=["symptom_description"],
        reasoning="Insufficient details provided to categorize or evaluate refund claim.",
    )
    mock_llm = make_mock_clarification_llm(expected_output)

    state = {
        "refund_id": "ref_email_node_test",
        "customer_request_text": "Watch has issues.",
        "category": "unclassified",
        "clarification_count": 0,
    }

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_llm)
            update = clarification_node(state)

        # Verify state storage of full email
        assert update["clarification_prompt"] == clarification_email
        assert "Dear Customer," in update["clarification_prompt"]
        assert "Sincerely," in update["clarification_prompt"]
        assert update["status"] == "awaiting_clarification"
        assert update["needs_clarification"] is True
        assert update["clarification_count"] == 1

        # Verify repo invocation with exact full email
        mock_repo.request_clarification.assert_called_once_with(
            refund_id="ref_email_node_test",
            clarification_prompt=clarification_email,
        )
    finally:
        set_current_repository(None)

