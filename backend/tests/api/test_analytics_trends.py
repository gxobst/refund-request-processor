"""Unit and integration tests for time-series trend analytics and date range filtering."""

from decimal import Decimal
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.db.repository import RefundRepository
from app.main import app
from app.schemas.analytics import AnalyticsMetricsResponse, AnalyticsTrendsResponse, TrendDataPoint


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


SAMPLE_ITEMS = [
    # 2026-10-01 (Week 40) - Auto Approved
    {
        "refund_id": "ref_01",
        "created_at": "2026-10-01T08:30:00Z",
        "status": "completed",
        "decision": "auto_approve",
        "confidence_score": Decimal("0.90"),
        "latency_ms": Decimal("100.0"),
    },
    # 2026-10-01 (Week 40) - Denied
    {
        "refund_id": "ref_02",
        "created_at": "2026-10-01T23:45:00Z",
        "status": "completed",
        "decision": "deny",
        "confidence_score": Decimal("0.80"),
        "latency_ms": Decimal("200.0"),
    },
    # 2026-10-02 (Week 40) - Escalated
    {
        "refund_id": "ref_03",
        "created_at": "2026-10-02T10:15:00Z",
        "status": "escalated",
        "decision": "escalate",
        "confidence_score": Decimal("0.70"),
        "node_latencies": {"classifier": Decimal("50.0"), "policy_checker": Decimal("100.0"), "decision_agent": Decimal("50.0")},
    },
    # 2026-10-08 (Week 41) - Auto Approved (using status='auto_approved')
    {
        "refund_id": "ref_04",
        "created_at": "2026-10-08T14:00:00Z",
        "status": "auto_approved",
        "decision": None,
        "confidence_score": Decimal("0.95"),
        "latency_ms": Decimal("150.0"),
    },
    # 2026-10-09 (Week 41) - Denied (using status='denied')
    {
        "refund_id": "ref_05",
        "created_at": "2026-10-09T18:00:00Z",
        "status": "denied",
        "decision": None,
        "confidence_score": Decimal("0.85"),
        "latency_ms": Decimal("250.0"),
    },
]


# ---------------------------------------------------------------------------
# Repository Unit Tests: Date Range Filtering & Trends
# ---------------------------------------------------------------------------

def test_repository_get_analytics_metrics_date_range_filter(repository_with_mock_table, mock_dynamo_table):
    """Verify get_analytics_metrics filters by start_date and end_date."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}

    # Filter to only 2026-10-01
    metrics = repository_with_mock_table.get_analytics_metrics(start_date="2026-10-01", end_date="2026-10-01")
    assert metrics.total_requests == 2
    assert metrics.decision_breakdown.auto_approve == 1
    assert metrics.decision_breakdown.deny == 1
    assert metrics.auto_approval_rate == 0.5

    # Filter to 2026-10-02 to 2026-10-08
    metrics_range = repository_with_mock_table.get_analytics_metrics(start_date="2026-10-02", end_date="2026-10-08")
    assert metrics_range.total_requests == 2  # ref_03 and ref_04


def test_repository_get_analytics_metrics_empty_match(repository_with_mock_table, mock_dynamo_table):
    """Verify get_analytics_metrics returns 0 metrics when no records fall in date range."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}

    metrics = repository_with_mock_table.get_analytics_metrics(start_date="2026-11-01", end_date="2026-11-30")
    assert metrics.total_requests == 0
    assert metrics.auto_approval_rate == 0.0
    assert metrics.average_confidence == 0.0
    assert metrics.average_latency_ms == 0.0


def test_repository_get_analytics_trends_daily(repository_with_mock_table, mock_dynamo_table):
    """Verify get_analytics_trends groups by daily period in chronological order."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}

    trends = repository_with_mock_table.get_analytics_trends(interval="daily")
    assert isinstance(trends, AnalyticsTrendsResponse)
    assert trends.interval == "daily"
    assert len(trends.points) == 4

    # Points should be sorted chronologically
    periods = [p.period for p in trends.points]
    assert periods == ["2026-10-01", "2026-10-02", "2026-10-08", "2026-10-09"]

    # Check 2026-10-01 bucket (2 requests: 1 auto_approve, 1 deny)
    p1 = trends.points[0]
    assert p1.period == "2026-10-01"
    assert p1.total_requests == 2
    assert p1.auto_approved == 1
    assert p1.denied == 1
    assert p1.escalated == 0
    assert p1.average_confidence == 0.85
    assert p1.average_latency_ms == 150.0

    # Check 2026-10-02 bucket (1 request: escalated, node latencies sum = 200.0)
    p2 = trends.points[1]
    assert p2.period == "2026-10-02"
    assert p2.total_requests == 1
    assert p2.escalated == 1
    assert p2.average_confidence == 0.70
    assert p2.average_latency_ms == 200.0


def test_repository_get_analytics_trends_weekly(repository_with_mock_table, mock_dynamo_table):
    """Verify get_analytics_trends groups by ISO calendar week (YYYY-Www)."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}

    trends = repository_with_mock_table.get_analytics_trends(interval="weekly")
    assert trends.interval == "weekly"
    assert len(trends.points) == 2

    # Week 40 has ref_01, ref_02, ref_03
    w40 = trends.points[0]
    assert w40.period == "2026-W40"
    assert w40.total_requests == 3
    assert w40.auto_approved == 1
    assert w40.denied == 1
    assert w40.escalated == 1
    assert round(w40.average_confidence, 4) == round((0.90 + 0.80 + 0.70) / 3, 4)

    # Week 41 has ref_04, ref_05
    w41 = trends.points[1]
    assert w41.period == "2026-W41"
    assert w41.total_requests == 2
    assert w41.auto_approved == 1
    assert w41.denied == 1
    assert w41.escalated == 0


def test_repository_get_analytics_trends_date_filtered(repository_with_mock_table, mock_dynamo_table):
    """Verify get_analytics_trends respects start_date and end_date filtering."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}

    trends = repository_with_mock_table.get_analytics_trends(
        start_date="2026-10-08", end_date="2026-10-09", interval="daily"
    )
    assert trends.start_date == "2026-10-08"
    assert trends.end_date == "2026-10-09"
    assert len(trends.points) == 2
    assert trends.points[0].period == "2026-10-08"
    assert trends.points[1].period == "2026-10-09"


def test_repository_get_analytics_trends_empty_table(repository_with_mock_table, mock_dynamo_table):
    """Verify get_analytics_trends returns empty points without error when table is empty."""
    mock_dynamo_table.scan.return_value = {"Items": []}

    trends = repository_with_mock_table.get_analytics_trends()
    assert trends.points == []
    assert trends.interval == "daily"


# ---------------------------------------------------------------------------
# API Route Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_get_metrics_with_date_range(client, mock_dynamo_table):
    """GET /v1/analytics/metrics passes start_date and end_date to repository."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        response = await client.get("/v1/analytics/metrics?start_date=2026-10-01&end_date=2026-10-01")
        assert response.status_code == 200
        data = response.json()
        assert data["total_requests"] == 2
        assert data["auto_approval_rate"] == 0.5
    finally:
        app.dependency_overrides.pop(get_repository, None)


@pytest.mark.asyncio
async def test_api_get_metrics_invalid_date_range_400(client):
    """GET /v1/analytics/metrics returns 400 Bad Request when start_date > end_date."""
    response = await client.get("/v1/analytics/metrics?start_date=2026-10-10&end_date=2026-10-01")
    assert response.status_code == 400
    assert "start_date cannot be after end_date" in response.text


@pytest.mark.asyncio
async def test_api_get_trends_daily_success(client, mock_dynamo_table):
    """GET /v1/analytics/trends returns daily trend aggregation."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        # Both /v1/analytics/trends and /analytics/trends should work
        for endpoint in ("/v1/analytics/trends", "/analytics/trends"):
            response = await client.get(f"{endpoint}?interval=daily")
            assert response.status_code == 200
            data = response.json()
            assert data["interval"] == "daily"
            assert len(data["points"]) == 4
            assert data["points"][0]["period"] == "2026-10-01"
            assert data["points"][0]["total_requests"] == 2
            assert data["points"][0]["auto_approved"] == 1
    finally:
        app.dependency_overrides.pop(get_repository, None)


@pytest.mark.asyncio
async def test_api_get_trends_weekly_success(client, mock_dynamo_table):
    """GET /v1/analytics/trends?interval=weekly returns weekly trend aggregation."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        response = await client.get("/v1/analytics/trends?interval=weekly")
        assert response.status_code == 200
        data = response.json()
        assert data["interval"] == "weekly"
        assert len(data["points"]) == 2
        assert data["points"][0]["period"] == "2026-W40"
    finally:
        app.dependency_overrides.pop(get_repository, None)


@pytest.mark.asyncio
async def test_api_get_trends_invalid_date_range_400(client):
    """GET /v1/analytics/trends returns 400 Bad Request when start_date > end_date."""
    response = await client.get("/v1/analytics/trends?start_date=2026-10-15&end_date=2026-10-01")
    assert response.status_code == 400
    assert "start_date cannot be after end_date" in response.text


@pytest.mark.asyncio
async def test_api_get_trends_invalid_interval_422(client):
    """GET /v1/analytics/trends returns 422 Unprocessable Entity when interval is invalid."""
    response = await client.get("/v1/analytics/trends?interval=monthly")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_api_get_trends_empty_table_200(client, mock_dynamo_table):
    """GET /v1/analytics/trends on empty table returns 200 with points: []."""
    mock_dynamo_table.scan.return_value = {"Items": []}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        response = await client.get("/v1/analytics/trends")
        assert response.status_code == 200
        data = response.json()
        assert data["points"] == []
    finally:
        app.dependency_overrides.pop(get_repository, None)
