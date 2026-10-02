"""Unit and integration tests for operational analytics and AI metrics API."""

from decimal import Decimal
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.db.repository import RefundRepository
from app.main import app
from app.schemas.analytics import AnalyticsMetricsResponse, DecisionBreakdown, StatusBreakdown


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
# Unit tests for RefundRepository.get_analytics_metrics()
# ---------------------------------------------------------------------------

def test_get_analytics_metrics_empty_table(repository_with_mock_table, mock_dynamo_table):
    """When the table contains 0 records, return all 0s, 0.0 rates, and empty category breakdown."""
    mock_dynamo_table.scan.return_value = {"Items": []}
    metrics = repository_with_mock_table.get_analytics_metrics()

    assert isinstance(metrics, AnalyticsMetricsResponse)
    assert metrics.total_requests == 0
    assert metrics.status_breakdown.pending == 0
    assert metrics.status_breakdown.completed == 0
    assert metrics.status_breakdown.escalated == 0
    assert metrics.status_breakdown.awaiting_clarification == 0

    assert metrics.decision_breakdown.auto_approve == 0
    assert metrics.decision_breakdown.deny == 0
    assert metrics.decision_breakdown.escalate == 0
    assert metrics.decision_breakdown.pending == 0

    assert metrics.auto_approval_rate == 0.0
    assert metrics.override_rate == 0.0
    assert metrics.average_confidence == 0.0
    assert metrics.category_breakdown == {}


def test_get_analytics_metrics_populated_records(repository_with_mock_table, mock_dynamo_table):
    """Verify aggregation on populated records across statuses, decisions, rates, and categories."""
    mock_items = [
        # Record 1: Completed, auto_approve, damaged, confidence 0.95
        {
            "refund_id": "ref_1",
            "order_id": "ORD-001",
            "status": "completed",
            "decision": "auto_approve",
            "confidence_score": Decimal("0.95"),
            "category": "damaged",
            "override_decision": None,
            "overridden_at": None,
        },
        # Record 2: Completed, deny, overridden to auto_approve, damaged, confidence 0.85
        {
            "refund_id": "ref_2",
            "order_id": "ORD-002",
            "status": "completed",
            "decision": "deny",
            "confidence_score": 0.85,
            "category": "damaged",
            "override_decision": "auto_approve",
            "overridden_at": "2026-10-01T12:00:00Z",
        },
        # Record 3: Completed, auto_approve, wrong_item, confidence 0.90
        {
            "refund_id": "ref_3",
            "order_id": "ORD-003",
            "status": "completed",
            "decision": "auto_approve",
            "confidence_score": 0.90,
            "category": "wrong_item",
            "override_decision": None,
            "overridden_at": None,
        },
        # Record 4: Escalated, escalate, late_delivery, confidence 0.70
        {
            "refund_id": "ref_4",
            "order_id": "ORD-004",
            "status": "escalated",
            "decision": "escalate",
            "confidence_score": 0.70,
            "category": "late_delivery",
            "override_decision": None,
            "overridden_at": None,
        },
        # Record 5: Awaiting clarification, decision None, category None, confidence None
        {
            "refund_id": "ref_5",
            "order_id": "ORD-005",
            "status": "awaiting_clarification",
            "decision": None,
            "confidence_score": None,
            "category": None,
            "override_decision": None,
            "overridden_at": None,
        },
        # Record 6: Pending, decision "pending", category "", confidence 0.60
        {
            "refund_id": "ref_6",
            "order_id": "ORD-006",
            "status": "pending",
            "decision": "pending",
            "confidence_score": Decimal("0.60"),
            "category": "   ",
            "override_decision": None,
            "overridden_at": None,
        },
    ]
    mock_dynamo_table.scan.return_value = {"Items": mock_items}

    metrics = repository_with_mock_table.get_analytics_metrics()

    assert metrics.total_requests == 6

    # Status breakdown
    assert metrics.status_breakdown.completed == 3
    assert metrics.status_breakdown.escalated == 1
    assert metrics.status_breakdown.awaiting_clarification == 1
    assert metrics.status_breakdown.pending == 1

    # Decision breakdown (records 5 and 6 mapped to pending)
    assert metrics.decision_breakdown.auto_approve == 2
    assert metrics.decision_breakdown.deny == 1
    assert metrics.decision_breakdown.escalate == 1
    assert metrics.decision_breakdown.pending == 2

    # auto_approval_rate = 2 / 6 = 0.3333
    assert metrics.auto_approval_rate == 0.3333

    # override_rate = 1 override among 3 completed records = 1 / 3 = 0.3333
    assert metrics.override_rate == 0.3333

    # average_confidence = (0.95 + 0.85 + 0.90 + 0.70 + 0.60) / 5 = 4.0 / 5 = 0.8000
    assert metrics.average_confidence == 0.8000

    # category_breakdown
    assert metrics.category_breakdown == {
        "damaged": 2,
        "wrong_item": 1,
        "late_delivery": 1,
        "unclassified": 2,
    }


def test_override_rate_only_considers_completed_records(repository_with_mock_table, mock_dynamo_table):
    """Override rate must only evaluate completed records, ignoring non-completed overrides."""
    mock_items = [
        # Escalated with override info (not completed)
        {
            "status": "escalated",
            "decision": "escalate",
            "override_decision": "auto_approve",
            "overridden_at": "2026-10-01T12:00:00Z",
        },
        # Completed without override
        {
            "status": "completed",
            "decision": "deny",
            "override_decision": None,
            "overridden_at": None,
        },
    ]
    mock_dynamo_table.scan.return_value = {"Items": mock_items}

    metrics = repository_with_mock_table.get_analytics_metrics()
    assert metrics.status_breakdown.completed == 1
    assert metrics.status_breakdown.escalated == 1
    # 0 out of 1 completed records have overrides
    assert metrics.override_rate == 0.0


def test_average_confidence_when_all_scores_none(repository_with_mock_table, mock_dynamo_table):
    """When no records have confidence scores, average_confidence is 0.0."""
    mock_items = [
        {"status": "pending", "confidence_score": None},
        {"status": "completed", "confidence_score": None},
    ]
    mock_dynamo_table.scan.return_value = {"Items": mock_items}

    metrics = repository_with_mock_table.get_analytics_metrics()
    assert metrics.average_confidence == 0.0


# ---------------------------------------------------------------------------
# API endpoint integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_analytics_metrics_endpoints_success(client: AsyncClient):
    """GET /v1/analytics/metrics and GET /analytics/metrics return HTTP 200 with valid schema."""
    fake_metrics = AnalyticsMetricsResponse(
        total_requests=10,
        status_breakdown=StatusBreakdown(pending=2, completed=5, escalated=2, awaiting_clarification=1),
        decision_breakdown=DecisionBreakdown(auto_approve=5, deny=2, escalate=2, pending=1),
        auto_approval_rate=0.5000,
        override_rate=0.2000,
        average_confidence=0.8850,
        category_breakdown={"damaged": 6, "wrong_item": 4},
    )

    mock_repo = MagicMock(spec=RefundRepository)
    mock_repo.get_analytics_metrics.return_value = fake_metrics

    app.dependency_overrides[get_repository] = lambda: mock_repo

    try:
        for path in ("/v1/analytics/metrics", "/analytics/metrics"):
            response = await client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["total_requests"] == 10
            assert data["status_breakdown"] == {
                "pending": 2,
                "completed": 5,
                "escalated": 2,
                "awaiting_clarification": 1,
            }
            assert data["decision_breakdown"] == {
                "auto_approve": 5,
                "deny": 2,
                "escalate": 2,
                "pending": 1,
            }
            assert data["auto_approval_rate"] == 0.5000
            assert data["override_rate"] == 0.2000
            assert data["average_confidence"] == 0.8850
            assert data["category_breakdown"] == {"damaged": 6, "wrong_item": 4}
    finally:
        app.dependency_overrides.pop(get_repository, None)
