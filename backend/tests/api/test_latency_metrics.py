"""Unit and integration tests for LLM inference latency tracking and operational latency metrics."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.db.repository import RefundRepository, _convert_floats_to_decimal, _convert_decimals_to_float
from app.graph.nodes import (
    classifier_node,
    decision_node,
    policy_checker_node,
    save_dynamo_node,
    set_current_repository,
)
from app.main import app
from app.schemas.analytics import AnalyticsMetricsResponse
from app.schemas.refund import RefundDecisionUpdate, RefundRecord


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_dynamo_table():
    """Mock DynamoDB table instance."""
    table = MagicMock()
    table.scan.return_value = {"Items": []}
    return table


@pytest.fixture
def repository_with_mock_table(mock_dynamo_table):
    """RefundRepository wired to mock table."""
    resource = MagicMock()
    resource.Table.return_value = mock_dynamo_table
    repo = RefundRepository(dynamodb_resource=resource, table_name="test_refunds")
    return repo


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Unit tests for Node Latency Tracking in Graph Nodes
# ---------------------------------------------------------------------------

def test_classifier_node_records_latency():
    """Unit test verifies classifier_node records non-negative execution latency into node_latencies."""
    state = {
        "customer_request_text": "I received broken headphones.",
        "order": {"order_id": "ORD-123"},
        "node_latencies": {},
    }
    with patch("app.graph.nodes.agent_classifier_node", return_value={
        "category": "damaged",
        "classification_confidence": 0.95,
        "classification_reasoning": "Product arrived damaged.",
    }):
        result = classifier_node(state)

    assert "node_latencies" in result
    assert "classifier" in result["node_latencies"]
    assert isinstance(result["node_latencies"]["classifier"], float)
    assert result["node_latencies"]["classifier"] >= 0.0


def test_policy_checker_node_records_latency():
    """Unit test verifies policy_checker_node records non-negative execution latency into node_latencies."""
    state = {
        "order": {"order_id": "ORD-123", "items": [{"name": "item"}]},
        "category": "damaged",
        "node_latencies": {"classifier": 45.2},
    }
    with patch("app.graph.nodes.agent_policy_checker_node", return_value={
        "policy_status": "pass",
        "matched_policy_rule": {},
        "tool_calls": [],
    }):
        result = policy_checker_node(state)

    assert "node_latencies" in result
    assert "policy_checker" in result["node_latencies"]
    assert isinstance(result["node_latencies"]["policy_checker"], float)
    assert result["node_latencies"]["policy_checker"] >= 0.0
    # Preserves existing classifier latency
    assert result["node_latencies"]["classifier"] == 45.2


def test_decision_node_records_latency():
    """Unit test verifies decision_node records non-negative execution latency into node_latencies."""
    state = {
        "order_id": "ORD-123",
        "refund_id": "ref_123",
        "policy_status": "pass",
        "confidence_score": 0.95,
        "category": "damaged",
        "node_latencies": {"classifier": 45.2, "policy_checker": 110.5},
    }
    with patch("app.graph.nodes.agent_decision_node", return_value={
        "decision": "auto_approve",
        "reasoning": "Order complies with refund policy.",
        "confidence_score": 0.95,
    }):
        result = decision_node(state)

    assert "node_latencies" in result
    assert "decision_agent" in result["node_latencies"]
    assert isinstance(result["node_latencies"]["decision_agent"], float)
    assert result["node_latencies"]["decision_agent"] >= 0.0
    # Preserves existing latencies
    assert result["node_latencies"]["classifier"] == 45.2
    assert result["node_latencies"]["policy_checker"] == 110.5


def test_save_dynamo_node_passes_latencies_to_update_decision():
    """Unit test verifies save_dynamo_node passes node_latencies and computed latency_ms to update_decision."""
    mock_repo = MagicMock()
    state = {
        "refund_id": "ref_latency_123",
        "order_id": "ORD-555",
        "decision": "auto_approve",
        "reasoning": "All checks passed.",
        "matched_policy_rule": {"refund_window_days": 30},
        "confidence_score": 0.98,
        "status": "completed",
        "tool_calls": [],
        "node_latencies": {
            "classifier": 120.5,
            "policy_checker": 350.25,
            "decision_agent": 210.25,
        },
    }

    set_current_repository(mock_repo)
    try:
        result = save_dynamo_node(state)
    finally:
        set_current_repository(None)

    assert result["status"] == "completed"
    assert result["node_latencies"] == state["node_latencies"]
    assert result["latency_ms"] == pytest.approx(681.0, 0.01)

    mock_repo.update_decision.assert_called_once()
    kwargs = mock_repo.update_decision.call_args.kwargs
    assert kwargs["refund_id"] == "ref_latency_123"
    assert kwargs["node_latencies"] == state["node_latencies"]
    assert kwargs["latency_ms"] == pytest.approx(681.0, 0.01)


# ---------------------------------------------------------------------------
# Unit tests for RefundRecord Legacy Deserialization and Update Schema
# ---------------------------------------------------------------------------

def test_refund_record_legacy_deserialization_without_latencies():
    """Unit test verifies RefundRecord deserializes legacy records missing latency attributes without errors."""
    legacy_payload = {
        "refund_id": "ref_legacy_001",
        "order_id": "ORD-999",
        "customer_request_text": "Item broke after 2 days.",
        "status": "completed",
        "decision": "auto_approve",
        "reasoning": "Valid return request.",
        "confidence_score": 0.9,
    }
    record = RefundRecord.model_validate(legacy_payload)
    assert record.node_latencies == {}
    assert record.latency_ms is None


def test_refund_decision_update_schema_accepts_latencies():
    """Unit test verifies RefundDecisionUpdate accepts optional latency fields."""
    update = RefundDecisionUpdate(
        decision="auto_approve",
        reasoning="Within policy.",
        confidence_score=0.95,
        status="completed",
        node_latencies={"classifier": 50.0, "decision_agent": 75.0},
        latency_ms=125.0,
    )
    assert update.node_latencies == {"classifier": 50.0, "decision_agent": 75.0}
    assert update.latency_ms == 125.0


# ---------------------------------------------------------------------------
# Unit tests for DynamoDB Persistence of Float Latencies as Decimal
# ---------------------------------------------------------------------------

def test_repository_update_decision_persists_latencies(repository_with_mock_table, mock_dynamo_table):
    """Unit test verifies update_decision converts latencies to Decimals and saves to DynamoDB."""
    existing_item = {
        "refund_id": "ref_persist_01",
        "order_id": "ORD-100",
        "customer_request_text": "Need refund.",
        "status": "pending",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
        "node_latencies": {},
        "latency_ms": None,
    }
    mock_dynamo_table.get_item.return_value = {"Item": existing_item}

    updated = repository_with_mock_table.update_decision(
        refund_id="ref_persist_01",
        decision="auto_approve",
        reasoning="Passed policy checks.",
        matched_policy_rule={"max_order_amount": 200},
        confidence_score=0.94,
        status="completed",
        node_latencies={"classifier": 125.5, "policy_checker": 320.0, "decision_agent": 200.25},
        latency_ms=645.75,
    )

    assert updated.node_latencies["classifier"] == 125.5
    assert updated.node_latencies["policy_checker"] == 320.0
    assert updated.node_latencies["decision_agent"] == 200.25
    assert updated.latency_ms == 645.75

    mock_dynamo_table.put_item.assert_called_once()
    saved_item = mock_dynamo_table.put_item.call_args.kwargs["Item"]
    assert isinstance(saved_item["latency_ms"], Decimal)
    assert saved_item["latency_ms"] == Decimal("645.75")
    assert isinstance(saved_item["node_latencies"]["classifier"], Decimal)
    assert saved_item["node_latencies"]["classifier"] == Decimal("125.5")


# ---------------------------------------------------------------------------
# Unit tests for RefundRepository.get_analytics_metrics() Latency Aggregation
# ---------------------------------------------------------------------------

def test_get_analytics_metrics_empty_table_returns_zero_latencies(repository_with_mock_table, mock_dynamo_table):
    """Unit test verifies get_analytics_metrics() returns average_latency_ms == 0.0 and zero node breakdowns on empty table."""
    mock_dynamo_table.scan.return_value = {"Items": []}
    metrics = repository_with_mock_table.get_analytics_metrics()

    assert metrics.average_latency_ms == 0.0
    assert metrics.node_latency_breakdown == {
        "classifier": 0.0,
        "policy_checker": 0.0,
        "decision_agent": 0.0,
    }


def test_get_analytics_metrics_aggregates_latencies(repository_with_mock_table, mock_dynamo_table):
    """Unit test verifies get_analytics_metrics() aggregates total and per-node latencies across full and partial records."""
    mock_items = [
        # Record 1: full latencies
        {
            "refund_id": "ref_1",
            "order_id": "ORD-001",
            "status": "completed",
            "decision": "auto_approve",
            "latency_ms": Decimal("1000.00"),
            "node_latencies": {
                "classifier": Decimal("200.00"),
                "policy_checker": Decimal("500.00"),
                "decision_agent": Decimal("300.00"),
            },
        },
        # Record 2: full latencies
        {
            "refund_id": "ref_2",
            "order_id": "ORD-002",
            "status": "completed",
            "decision": "deny",
            "latency_ms": Decimal("1600.00"),
            "node_latencies": {
                "classifier": Decimal("300.00"),
                "policy_checker": Decimal("700.00"),
                "decision_agent": Decimal("600.00"),
            },
        },
        # Record 3: partial node latencies (no decision_agent), latency_ms computed from node sum
        {
            "refund_id": "ref_3",
            "order_id": "ORD-003",
            "status": "escalated",
            "decision": "escalate",
            "latency_ms": None,
            "node_latencies": {
                "classifier": Decimal("100.00"),
                "policy_checker": Decimal("300.00"),
            },
        },
        # Record 4: legacy record without any latency fields
        {
            "refund_id": "ref_4",
            "order_id": "ORD-004",
            "status": "pending",
            "decision": "pending",
        },
    ]
    mock_dynamo_table.scan.return_value = {"Items": mock_items}

    metrics = repository_with_mock_table.get_analytics_metrics()

    # Latencies considered: Record 1 (1000.0), Record 2 (1600.0), Record 3 (100 + 300 = 400.0)
    # Mean = (1000.0 + 1600.0 + 400.0) / 3 = 3000.0 / 3 = 1000.0
    assert metrics.average_latency_ms == 1000.0

    # Node breakdowns:
    # classifier: (200 + 300 + 100) / 3 = 200.0
    # policy_checker: (500 + 700 + 300) / 3 = 500.0
    # decision_agent: (300 + 600) / 2 = 450.0
    assert metrics.node_latency_breakdown["classifier"] == 200.0
    assert metrics.node_latency_breakdown["policy_checker"] == 500.0
    assert metrics.node_latency_breakdown["decision_agent"] == 450.0


# ---------------------------------------------------------------------------
# Integration test for GET /v1/analytics/metrics API Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_analytics_metrics_endpoint_includes_latency(client):
    """Integration test verifies GET /v1/analytics/metrics returns HTTP 200 with average_latency_ms and node_latency_breakdown."""
    mock_repo = MagicMock(spec=RefundRepository)
    mock_repo.get_analytics_metrics.return_value = AnalyticsMetricsResponse(
        total_requests=10,
        average_latency_ms=1240.55,
        node_latency_breakdown={
            "classifier": 210.25,
            "policy_checker": 530.10,
            "decision_agent": 500.20,
        },
    )

    app.dependency_overrides[get_repository] = lambda: mock_repo
    try:
        response = await client.get("/v1/analytics/metrics")
        assert response.status_code == 200
        payload = response.json()
        assert "average_latency_ms" in payload
        assert payload["average_latency_ms"] == 1240.55
        assert "node_latency_breakdown" in payload
        assert payload["node_latency_breakdown"]["classifier"] == 210.25
        assert payload["node_latency_breakdown"]["policy_checker"] == 530.10
        assert payload["node_latency_breakdown"]["decision_agent"] == 500.20
    finally:
        app.dependency_overrides.clear()
