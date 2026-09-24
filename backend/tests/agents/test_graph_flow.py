"""Unit tests for the multi-agent LangGraph workflow orchestration and checkpointing."""

import boto3
from decimal import Decimal
from unittest.mock import MagicMock, patch
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
import pytest

from app.core.config import Settings
from app.graph.checkpoint import get_checkpointer
from app.graph.nodes import (
    _lookup_order_data,
    intake_validate_node,
    set_current_repository,
)
from app.agents.clarification import ClarificationOutput
from app.graph.runner import run_refund_workflow
from app.graph.workflow import build_refund_graph, route_classifier
from app.schemas.classifier import ClassificationOutput
from app.schemas.policy_checker import PolicyCheckerOutput
from langchain_core.messages import AIMessage, ToolMessage
from tests.agents.test_policy_checker import MockToolCallingLLM




def make_mock_llm(output: ClassificationOutput) -> MagicMock:
    """Helper creating a mocked BaseChatModel returning a structured ClassificationOutput."""
    mock = MagicMock()
    mock.with_structured_output.return_value = RunnableLambda(lambda _: output)
    return mock


def make_mock_clarification_llm(output: ClarificationOutput) -> MagicMock:
    """Helper creating a mocked BaseChatModel returning a structured ClarificationOutput."""
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


def test_route_classifier_router_logic():
    # Low confidence (< 0.70) with count 0 -> clarification
    assert route_classifier({"confidence_score": 0.5, "clarification_count": 0}) == "clarification"
    # Low confidence with count 1 -> clarification
    assert route_classifier({"confidence_score": 0.5, "clarification_count": 1}) == "clarification"
    # Low confidence with count 2 -> decision
    assert route_classifier({"confidence_score": 0.5, "clarification_count": 2}) == "decision"
    # Low confidence with count 3 -> decision
    assert route_classifier({"confidence_score": 0.5, "clarification_count": 3}) == "decision"
    # is_low_confidence True with count 0 -> clarification
    assert route_classifier({"is_low_confidence": True, "clarification_count": 0}) == "clarification"
    # is_low_confidence True with count 2 -> decision
    assert route_classifier({"is_low_confidence": True, "clarification_count": 2}) == "decision"
    # Boundary 0.70 -> policy_checker
    assert route_classifier({"confidence_score": 0.70, "clarification_count": 0}) == "policy_checker"
    # High confidence 0.95 with count 2 -> policy_checker
    assert route_classifier({"confidence_score": 0.95, "clarification_count": 2}) == "policy_checker"


@pytest.mark.asyncio
async def test_workflow_low_confidence_routes_to_clarification_initial():
    """AC 1074: Low confidence (< 0.70) and count 0 routes to clarification and pauses."""
    # Arrange
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.45,
        reasoning="Vague request.",
    )
    mock_clarification = ClarificationOutput(
        clarification_prompt="Could you please upload a photo of the damaged item?",
        missing_aspects=["photos"],
        reasoning="Need photo evidence.",
    )
    mock_llm = make_mock_llm(mock_classification)
    mock_clarify_llm = make_mock_clarification_llm(mock_clarification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)
        mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_clarify_llm)

        graph = build_refund_graph(checkpointer=checkpointer)
        initial_state = {
            "refund_id": "ref_test_clarify_0",
            "order_id": "ORD-1001",
            "customer_request_text": "Not sure what happened but need refund.",
            "status": "pending",
            "clarification_count": 0,
        }
        config = {"configurable": {"thread_id": "thread_clarify_0"}}
        final_state = await graph.ainvoke(initial_state, config=config)

    # Assert: pauses at clarification node, count becomes 1
    assert final_state["status"] == "awaiting_clarification"
    assert final_state["clarification_count"] == 1
    assert final_state["needs_clarification"] is True
    assert final_state["clarification_prompt"] == "Could you please upload a photo of the damaged item?"
    assert final_state.get("decision") is None


@pytest.mark.asyncio
async def test_workflow_low_confidence_routes_to_clarification_second_attempt():
    """AC 1075: Low confidence (< 0.70) and initial count 1 routes to clarification, count becomes 2."""
    # Arrange
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.55,
        reasoning="Still somewhat unclear.",
    )
    mock_clarification = ClarificationOutput(
        clarification_prompt="Could you confirm the serial number?",
        missing_aspects=["serial_number"],
        reasoning="Unclear item identity.",
    )
    mock_llm = make_mock_llm(mock_classification)
    mock_clarify_llm = make_mock_clarification_llm(mock_clarification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)
        mp.setattr("app.agents.clarification.get_bedrock_llm", lambda: mock_clarify_llm)

        graph = build_refund_graph(checkpointer=checkpointer)
        initial_state = {
            "refund_id": "ref_test_clarify_1",
            "order_id": "ORD-1001",
            "customer_request_text": "Item not working right.",
            "status": "pending",
            "clarification_count": 1,
        }
        config = {"configurable": {"thread_id": "thread_clarify_1"}}
        final_state = await graph.ainvoke(initial_state, config=config)

    # Assert: pauses at clarification node, count becomes 2
    assert final_state["status"] == "awaiting_clarification"
    assert final_state["clarification_count"] == 2
    assert final_state["needs_clarification"] is True
    assert final_state["clarification_prompt"] == "Could you confirm the serial number?"


@pytest.mark.asyncio
async def test_workflow_low_confidence_exhausted_clarification_escalates():
    """AC 1076: Low confidence (< 0.70) with count 2 bypasses clarification, routes to decision -> escalates."""
    # Arrange
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.45,
        reasoning="Repeatedly ambiguous request.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        graph = build_refund_graph(checkpointer=checkpointer)
        initial_state = {
            "refund_id": "ref_test_clarify_exhausted",
            "order_id": "ORD-1001",
            "customer_request_text": "Still not clear.",
            "status": "pending",
            "clarification_count": 2,
        }
        config = {"configurable": {"thread_id": "thread_clarify_exhausted"}}
        final_state = await graph.ainvoke(initial_state, config=config)

    # Assert: routed to decision, escalated
    assert final_state["decision"] == "escalate"
    assert final_state["status"] == "escalated"
    assert final_state["is_low_confidence"] is True
    assert "confidence" in final_state["reasoning"].lower()


@pytest.mark.asyncio
async def test_workflow_boundary_confidence_routes_to_policy_checker():
    """AC 1077: Exact boundary confidence 0.70 routes to policy_checker rather than clarification."""
    # Arrange
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.70,
        reasoning="Adequately described issue.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        graph = build_refund_graph(checkpointer=checkpointer)
        initial_state = {
            "refund_id": "ref_test_boundary_70",
            "order_id": "ORD-1001",
            "customer_request_text": "Armrest broke during shipping.",
            "status": "pending",
            "clarification_count": 0,
        }
        config = {"configurable": {"thread_id": "thread_boundary_70"}}
        final_state = await graph.ainvoke(initial_state, config=config)

    # Assert: passed to policy checker -> auto_approve
    assert final_state["status"] == "completed"
    assert final_state["decision"] == "auto_approve"
    assert final_state["policy_status"] == "pass"
    assert final_state.get("clarification_prompt") is None


@pytest.mark.asyncio
async def test_workflow_high_confidence_with_count_2_routes_to_policy_checker():
    """AC 1078: High confidence (>= 0.70) with count 2 routes to policy_checker and reaches normal completion."""
    # Arrange
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Clear explanation with photo details.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        graph = build_refund_graph(checkpointer=checkpointer)
        initial_state = {
            "refund_id": "ref_test_high_conf_resumed",
            "order_id": "ORD-1001",
            "customer_request_text": "The armrest arrived snapped in half as seen in attached photos.",
            "status": "pending",
            "clarification_count": 2,
        }
        config = {"configurable": {"thread_id": "thread_high_conf_resumed"}}
        final_state = await graph.ainvoke(initial_state, config=config)

    # Assert: routes to policy_checker and auto-approves
    assert final_state["status"] == "completed"
    assert final_state["decision"] == "auto_approve"
    assert final_state["policy_status"] == "pass"


@pytest.mark.asyncio
async def test_workflow_escalation_flow_on_missing_order():
    # Arrange: Order ID does not exist in dataset
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Damaged item.",
    )
    mock_llm = make_mock_llm(mock_classification)
    mock_policy_llm = MagicMock()
    mock_policy_llm.with_structured_output.return_value = RunnableLambda(
        lambda _: PolicyCheckerOutput(
            policy_status="ambiguous",
            passed_rules=[],
            failed_rules=[],
            policy_reasoning="Missing required order data.",
        )
    )
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)
        mp.setattr("app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm)

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


def test_get_checkpointer_defaults_to_memory_saver_when_app_env_test():
    # Arrange
    settings = Settings(app_env="test")

    # Act
    saver = get_checkpointer(settings=settings)

    # Assert
    assert isinstance(saver, MemorySaver)


def test_get_checkpointer_dynamo_instantiation_with_settings():
    # Arrange
    fake_saver = MagicMock()
    settings = Settings(
        aws_region="eu-west-1",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        aws_session_token="test-session-token",
        dynamodb_table_checkpoints="custom-checkpoints-table",
        dynamodb_endpoint_url="http://localhost:8000",
        app_env="production",
    )

    with patch("langgraph_checkpoint_aws.DynamoDBSaver", return_value=fake_saver) as mock_dynamo_cls:
        # Act
        saver = get_checkpointer(use_dynamodb=True, settings=settings)

        # Assert
        assert saver == fake_saver
        mock_dynamo_cls.assert_called_once()
        call_kwargs = mock_dynamo_cls.call_args[1]
        assert call_kwargs["table_name"] == "custom-checkpoints-table"
        assert call_kwargs["region_name"] == "eu-west-1"
        assert call_kwargs["endpoint_url"] == "http://localhost:8000"
        session = call_kwargs.get("session")
        assert session is not None
        assert isinstance(session, boto3.Session)
        credentials = session.get_credentials()
        assert credentials.access_key == "test-access-key"
        assert credentials.secret_key == "test-secret-key"
        assert credentials.token == "test-session-token"


def test_get_checkpointer_explicit_table_name_overrides_settings():
    # Arrange
    fake_saver = MagicMock()
    settings = Settings(dynamodb_table_checkpoints="default-checkpoints-table")

    with patch("langgraph_checkpoint_aws.DynamoDBSaver", return_value=fake_saver) as mock_dynamo_cls:
        # Act
        saver = get_checkpointer(
            use_dynamodb=True, table_name="override-checkpoints-table", settings=settings
        )

        # Assert
        assert saver == fake_saver
        call_kwargs = mock_dynamo_cls.call_args[1]
        assert call_kwargs["table_name"] == "override-checkpoints-table"


def test_get_checkpointer_dynamo_without_credentials_omits_session_and_endpoint():
    # Arrange
    fake_saver = MagicMock()
    settings = Settings(
        aws_region="us-east-1",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        dynamodb_endpoint_url=None,
    )

    with patch("langgraph_checkpoint_aws.DynamoDBSaver", return_value=fake_saver) as mock_dynamo_cls:
        # Act
        saver = get_checkpointer(use_dynamodb=True, settings=settings)

        # Assert
        assert saver == fake_saver
        call_kwargs = mock_dynamo_cls.call_args[1]
        assert call_kwargs["table_name"] == "langgraph-checkpoints"
        assert call_kwargs["region_name"] == "us-east-1"
        assert "session" not in call_kwargs
        assert "endpoint_url" not in call_kwargs


def test_get_checkpointer_dynamo_exception_fallback_to_memory_saver():
    # Arrange: DynamoDBSaver raises an exception upon initialization
    with patch(
        "langgraph_checkpoint_aws.DynamoDBSaver",
        side_effect=Exception("Failed to connect to DynamoDB checkpoints table"),
    ):
        # Act
        saver = get_checkpointer(use_dynamodb=True)

        # Assert: Gracefully falls back to MemorySaver
        assert isinstance(saver, MemorySaver)


@pytest.mark.asyncio
async def test_run_refund_workflow_defaults_to_memory_saver_when_app_env_test():
    # Arrange
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Valid report.",
    )
    mock_llm = make_mock_llm(mock_classification)
    mock_settings = Settings(app_env="test")

    with patch("app.graph.runner.get_settings", return_value=mock_settings), \
         patch("app.graph.runner.get_checkpointer", wraps=get_checkpointer) as spy_get_checkpointer, \
         pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act: Execute workflow without passing explicit checkpointer
        final_state = await run_refund_workflow(
            refund_id="ref_test_default_checkpointer",
            order_id="ORD-1001",
            customer_request_text="The chair arrived broken.",
        )

        # Assert: Workflow completed and get_checkpointer was called with use_dynamodb=False
        assert final_state["status"] == "completed"
        spy_get_checkpointer.assert_called_once_with(
            use_dynamodb=False, settings=mock_settings
        )


@pytest.mark.asyncio
async def test_run_refund_workflow_uses_explicit_checkpointer_bypassing_factory():
    # Arrange
    explicit_checkpointer = MemorySaver()
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Valid report.",
    )
    mock_llm = make_mock_llm(mock_classification)

    with patch("app.graph.runner.get_checkpointer") as mock_get_checkpointer, \
         pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        # Act: Execute workflow with explicit checkpointer
        final_state = await run_refund_workflow(
            refund_id="ref_test_explicit_checkpointer",
            order_id="ORD-1001",
            customer_request_text="The chair arrived broken.",
            checkpointer=explicit_checkpointer,
        )

        # Assert: get_checkpointer was never invoked
        assert final_state["status"] == "completed"
        mock_get_checkpointer.assert_not_called()


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


def test_lookup_order_data_empty_or_none():
    # Arrange & Act & Assert
    assert _lookup_order_data("") is None
    assert _lookup_order_data(None) is None
    assert _lookup_order_data("   ") is None


def test_lookup_order_data_from_dynamodb_with_decimal_conversion():
    # Arrange: Mock DynamoDB item with Decimals
    mock_item = {
        "order_id": "ORD-DYNAMO-100",
        "item": "Premium Desk",
        "order_amount": Decimal("450.75"),
        "delivery_status": "delivered",
        "purchase_date": "2026-09-01",
        "quantity": Decimal("1"),
    }
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": mock_item}
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table

    mock_repo = MagicMock()
    mock_repo.dynamodb_resource = mock_resource

    # Act
    set_current_repository(mock_repo)
    try:
        result = _lookup_order_data("ORD-DYNAMO-100")
    finally:
        set_current_repository(None)

    # Assert
    mock_table.get_item.assert_called_once_with(Key={"order_id": "ORD-DYNAMO-100"})
    assert result is not None
    assert result["order_id"] == "ORD-DYNAMO-100"
    assert isinstance(result["order_amount"], float)
    assert result["order_amount"] == 450.75
    assert isinstance(result["quantity"], int)
    assert result["quantity"] == 1


def test_lookup_order_data_initializes_boto3_resource_when_no_active_repository():
    # Arrange: No repo in context, boto3.resource is called with settings
    mock_item = {
        "order_id": "ORD-DYNAMO-200",
        "order_amount": Decimal("100.00"),
    }
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": mock_item}
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table

    set_current_repository(None)
    with patch("boto3.resource", return_value=mock_resource) as mock_boto3_resource:
        # Act
        result = _lookup_order_data("ORD-DYNAMO-200")

    # Assert
    mock_boto3_resource.assert_called_once()
    mock_table.get_item.assert_called_once_with(Key={"order_id": "ORD-DYNAMO-200"})
    assert result is not None
    assert result["order_id"] == "ORD-DYNAMO-200"
    assert result["order_amount"] == 100


def test_lookup_order_data_fallback_to_json_on_dynamodb_exception():
    # Arrange: DynamoDB raises an exception (e.g. connection error)
    mock_table = MagicMock()
    mock_table.get_item.side_effect = Exception("DynamoDB connection error")
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    mock_repo = MagicMock()
    mock_repo.dynamodb_resource = mock_resource

    set_current_repository(mock_repo)
    try:
        # Act: ORD-1001 exists in mock_orders.json
        result = _lookup_order_data("ORD-1001")
    finally:
        set_current_repository(None)

    # Assert: successfully falls back to mock_orders.json
    assert result is not None
    assert result["order_id"] == "ORD-1001"
    assert result["delivery_status"] == "delivered"


def test_lookup_order_data_fallback_to_json_when_not_in_dynamodb():
    # Arrange: DynamoDB returns no item
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    mock_repo = MagicMock()
    mock_repo.dynamodb_resource = mock_resource

    set_current_repository(mock_repo)
    try:
        # Act: ORD-1001 exists in mock_orders.json
        result = _lookup_order_data("ORD-1001")
    finally:
        set_current_repository(None)

    # Assert: retrieved from mock_orders.json
    assert result is not None
    assert result["order_id"] == "ORD-1001"


def test_lookup_order_data_returns_none_when_in_neither():
    # Arrange: item neither in DynamoDB nor in mock_orders.json
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    mock_repo = MagicMock()
    mock_repo.dynamodb_resource = mock_resource

    set_current_repository(mock_repo)
    try:
        # Act
        result = _lookup_order_data("NONEXISTENT-ORDER-0000")
    finally:
        set_current_repository(None)

    # Assert
    assert result is None


def test_intake_validate_node_populates_missing_order_data_flags():
    # Arrange: mock DynamoDB order
    mock_item = {
        "order_id": "ORD-FOUND-1",
        "order_amount": Decimal("50.00"),
    }
    mock_table = MagicMock()
    mock_table.get_item.side_effect = lambda Key: (
        {"Item": mock_item} if Key.get("order_id") == "ORD-FOUND-1" else {}
    )
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    mock_repo = MagicMock()
    mock_repo.dynamodb_resource = mock_resource

    set_current_repository(mock_repo)
    try:
        # Act 1: Order found
        state_found = {"order_id": "ORD-FOUND-1"}
        res_found = intake_validate_node(state_found)

        # Act 2: Order missing
        state_missing = {"order_id": "NONEXISTENT-ORD-9999"}
        res_missing = intake_validate_node(state_missing)
    finally:
        set_current_repository(None)

    # Assert
    assert res_found["missing_order_data"] is False
    assert res_found["order"] is not None
    assert state_found["missing_order_data"] is False

    assert res_missing["missing_order_data"] is True
    assert res_missing["order"] is None
    assert state_missing["missing_order_data"] is True


@pytest.mark.asyncio
async def test_workflow_with_dynamodb_order_lookup():
    # Arrange: DynamoDB provides order data with Decimal amounts
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Damaged item photo provided.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    dynamo_order = {
        "order_id": "ORD-LIVE-DYNAMO-1",
        "item": "Monitor Arm",
        "purchase_date": "2026-09-01",
        "delivery_date": "2026-09-03",
        "delivery_status": "delivered",
        "order_amount": Decimal("120.00"),
    }
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": dynamo_order}
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    mock_repo = MagicMock()
    mock_repo.dynamodb_resource = mock_resource

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

        final_state = await run_refund_workflow(
            refund_id="ref_dynamo_test",
            order_id="ORD-LIVE-DYNAMO-1",
            customer_request_text="Monitor arm bent on arrival.",
            checkpointer=checkpointer,
            repository=mock_repo,
        )

    # Assert: Order was populated from DynamoDB with Decimal converted
    assert final_state["missing_order_data"] is False
    assert final_state["order"]["order_id"] == "ORD-LIVE-DYNAMO-1"
    assert final_state["order"]["order_amount"] == 120
    assert final_state["decision"] == "auto_approve"
    assert final_state["status"] == "completed"


@pytest.mark.asyncio
async def test_workflow_late_delivery_tool_calling_auto_approve():
    """AC 1276: End-to-end LangGraph workflow routes through policy_checker_node with simulated tool calling for late delivery, completing with status=='completed' and decision=='auto_approve'."""
    # Arrange: customer reporting late delivery for in-transit order ORD-1005 ($199.99 <= $300 limit)
    mock_classification = ClassificationOutput(
        category="late_delivery",
        confidence_score=0.94,
        reasoning="Customer reporting late delivery of in-transit item.",
    )
    mock_classifier_llm = make_mock_llm(mock_classification)

    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1005"},
            "id": "call_trk_flow_1005",
        }],
    )
    policy_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Carrier tracking confirmed shipment is delayed in transit past expected delivery.",
    )
    mock_policy_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=policy_output)
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_classifier_llm)
        mp.setattr("app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm)

        final_state = await run_refund_workflow(
            refund_id="ref_test_late_flow",
            order_id="ORD-1005",
            customer_request_text="My order has been delayed for over a week and hasn't arrived.",
            checkpointer=checkpointer,
        )

    # Assert: completes auto_approve with late_delivery category
    assert final_state["status"] == "completed"
    assert final_state["decision"] == "auto_approve"
    assert final_state["category"] == "late_delivery"
    assert final_state["policy_status"] == "pass"
    assert len(mock_policy_llm.invocations) >= 2
    # Verify carrier tool was called and result received
    tool_messages = [m for m in mock_policy_llm.invocations[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "TRK-1005" in tool_messages[0].content


@pytest.mark.asyncio
async def test_workflow_clear_cut_pass_bypasses_tools():
    """AC 1277: Clear-cut passing request completes workflow without invoking LLM or tools."""
    # Arrange: ORD-1001 is damaged, delivered recently, $250 <= $500
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Clear damage reported.",
    )
    mock_classifier_llm = make_mock_llm(mock_classification)
    mock_policy_llm = MagicMock()
    checkpointer = MemorySaver()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_classifier_llm)
        mp.setattr("app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm)

        final_state = await run_refund_workflow(
            refund_id="ref_test_bypass_tools",
            order_id="ORD-1001",
            customer_request_text="The armrest on the chair broke during transit.",
            checkpointer=checkpointer,
        )

    # Assert: completes auto_approve
    assert final_state["status"] == "completed"
    assert final_state["decision"] == "auto_approve"
    assert final_state["policy_status"] == "pass"
    # Verify policy checker LLM was never called because deterministic pass bypassed it
    mock_policy_llm.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_auto_approve_generates_and_persists_approval_email_text():
    """AC 1951: Verify that an auto-approved workflow run outputs approval_email_text in final state and persists it to DynamoDB."""
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Customer reported damaged item with clear evidence.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    # Mock DynamoDB repository to verify persistence
    mock_repo = MagicMock(spec=["update_decision"])
    set_current_repository(mock_repo)

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

            final_state = await run_refund_workflow(
                refund_id="ref_test_email_persistence",
                order_id="ORD-1001",
                customer_request_text="Chair arrived damaged.",
                checkpointer=checkpointer,
            )

        # Assert final workflow state
        assert final_state["decision"] == "auto_approve"
        assert final_state["status"] == "completed"
        assert "approval_email_text" in final_state
        assert final_state["approval_email_text"] is not None
        assert "Dear Customer," in final_state["approval_email_text"]
        assert "ORD-1001" in final_state["approval_email_text"]
        assert "RMA" in final_state["approval_email_text"]
        assert "14-day" in final_state["approval_email_text"]

        # Assert repository persistence
        mock_repo.update_decision.assert_called_once()
        kwargs = mock_repo.update_decision.call_args[1]
        assert kwargs["refund_id"] == "ref_test_email_persistence"
        assert kwargs["decision"] == "auto_approve"
        assert kwargs["approval_email_text"] == final_state["approval_email_text"]
    finally:
        set_current_repository(None)


@pytest.mark.asyncio
async def test_workflow_order_amount_exceeded_escalates():
    """AC 2311: Integration test asserts end-to-end workflow execution for an order exceeding max_order_amount produces decision='escalate' and status='escalated'."""
    # ORD-1003 has order_amount: 750.0 (exceeds $500 limit for damaged), delivered recently
    mock_classification = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Customer reported broken screen on monitor.",
    )
    mock_llm = make_mock_llm(mock_classification)
    checkpointer = MemorySaver()

    mock_repo = MagicMock(spec=["update_decision"])
    set_current_repository(mock_repo)

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

            final_state = await run_refund_workflow(
                refund_id="ref_test_amount_escalate",
                order_id="ORD-1003",
                customer_request_text="The gaming monitor screen is cracked.",
                checkpointer=checkpointer,
            )

        # Assert final workflow state
        assert final_state["decision"] == "escalate"
        assert final_state["status"] == "escalated"
        assert final_state["policy_status"] == "ambiguous"
        assert final_state["failed_rules"] == ["max_order_amount"]
        assert "supervisor" in final_state["policy_reasoning"].lower()

        # Assert persistence to DynamoDB
        mock_repo.update_decision.assert_called_once()
        kwargs = mock_repo.update_decision.call_args[1]
        assert kwargs["refund_id"] == "ref_test_amount_escalate"
        assert kwargs["decision"] == "escalate"
        assert kwargs["status"] == "escalated"
    finally:
        set_current_repository(None)




