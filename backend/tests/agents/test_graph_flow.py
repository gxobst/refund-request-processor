"""Unit tests for the multi-agent LangGraph workflow orchestration and checkpointing."""

from unittest.mock import MagicMock
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
import pytest

from app.graph.checkpoint import get_checkpointer
from app.graph.runner import run_refund_workflow
from app.graph.workflow import build_refund_graph
from app.schemas.classifier import ClassificationOutput


def make_mock_llm(output: ClassificationOutput) -> MagicMock:
    """Helper creating a mocked BaseChatModel returning a structured ClassificationOutput."""
    mock = MagicMock()
    mock.with_structured_output.return_value = RunnableLambda(lambda _: output)
    return mock


@pytest.mark.asyncio
async def test_workflow_auto_approve_flow():
    # Arrange: ORD-1001 is a delivered recent order for $250 (within $500 damaged limit)
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Customer clearly reported damaged item with photo proof.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act: run workflow
        final_state = await run_refund_workflow(
            refund_id="ref_test_approve",
            order_id="ORD-1001",
            customer_request_text="The armrest on the chair broke during transit.",
            checkpointer=checkpointer,
        )

    # Assert
    assert final_state["decision"] == "auto_approve"
    assert final_state["status"] == "completed"
    assert final_state["category"] == "damaged"
    assert final_state["policy_status"] == "pass"
    assert "approved" in final_state["reasoning"].lower()
    assert final_state["confidence_score"] == 0.95


@pytest.mark.asyncio
async def test_workflow_denied_flow():
    # Arrange: ORD-1004 has an expired delivery date (August 2026, > 30 days)
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.92,
        reasoning="Customer reported damaged item after window.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act: run workflow
        final_state = await run_refund_workflow(
            refund_id="ref_test_deny",
            order_id="ORD-1004",
            customer_request_text="The keyboard switch broke.",
            checkpointer=checkpointer,
        )

    # Assert
    assert final_state["decision"] == "deny"
    assert final_state["status"] == "completed"
    assert final_state["category"] == "damaged"
    assert final_state["policy_status"] == "fail"
    assert "refund_window_days" in final_state["failed_rules"]
    assert "denied" in final_state["reasoning"].lower()


@pytest.mark.asyncio
async def test_workflow_escalation_flow_on_low_confidence():
    # Arrange: Low classifier confidence (< 0.70)
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.45,
        reasoning="Vague request.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act: run workflow
        final_state = await run_refund_workflow(
            refund_id="ref_test_escalate_conf",
            order_id="ORD-1001",
            customer_request_text="Not sure what happened but need refund.",
            checkpointer=checkpointer,
        )

    # Assert
    assert final_state["decision"] == "escalate"
    assert final_state["status"] == "escalated"
    assert final_state["is_low_confidence"] is True
    assert "confidence" in final_state["reasoning"].lower()


@pytest.mark.asyncio
async def test_workflow_escalation_flow_on_missing_order():
    # Arrange: Order ID does not exist in dataset
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Damaged item.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act
        final_state = await run_refund_workflow(
            refund_id="ref_test_escalate_order",
            order_id="NONEXISTENT-ORD-9999",
            customer_request_text="Item broke.",
            checkpointer=checkpointer,
        )

    # Assert
    assert final_state["decision"] == "escalate"
    assert final_state["status"] == "escalated"
    assert final_state["missing_order_data"] is True


def test_get_checkpointer_memory_default():
    # Arrange & Act
    saver = get_checkpointer(use_dynamodb=False)

    # Assert
    assert isinstance(saver, MemorySaver)


def test_get_checkpointer_dynamo_option():
    # Arrange & Act: should return DynamoDBSaver or fallback without error
    saver = get_checkpointer(use_dynamodb=True, table_name="test-checkpoints")

    # Assert
    assert saver is not None


@pytest.mark.asyncio
async def test_workflow_state_persisted_in_checkpointer():
    # Arrange
    checkpointer = MemorySaver()
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Valid report.",
    )
    mock_llm = make_mock_llm(mock_classification)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act: run workflow with specific thread ID
        _ = await run_refund_workflow(
            refund_id="ref_checkpoint_123",
            order_id="ORD-1001",
            customer_request_text="Item cracked.",
            thread_id="thread_abc_1",
            checkpointer=checkpointer,
        )

    # Assert: retrieve checkpoint state using graph
    graph = build_refund_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "thread_abc_1"}}
    state_snapshot = graph.get_state(config)

    assert state_snapshot is not None
    assert state_snapshot.values["refund_id"] == "ref_checkpoint_123"
    assert state_snapshot.values["decision"] == "auto_approve"
