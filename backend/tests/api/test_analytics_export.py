"""Unit and integration tests for operational analytics CSV and PDF export endpoints."""

from datetime import datetime, timezone
from decimal import Decimal
import io
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.analytics import _format_analytics_csv, _format_analytics_pdf
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
    # 2026-10-01 - Damaged / Auto Approved
    {
        "refund_id": "ref_01",
        "created_at": "2026-10-01T08:30:00Z",
        "status": "completed",
        "decision": "auto_approve",
        "category": "damaged",
        "confidence_score": Decimal("0.90"),
        "latency_ms": Decimal("100.0"),
        "node_latencies": {"classifier": Decimal("30.0"), "policy_checker": Decimal("40.0"), "decision_agent": Decimal("30.0")},
    },
    # 2026-10-01 - Wrong Item / Denied
    {
        "refund_id": "ref_02",
        "created_at": "2026-10-01T23:45:00Z",
        "status": "completed",
        "decision": "deny",
        "category": "wrong_item",
        "confidence_score": Decimal("0.80"),
        "latency_ms": Decimal("200.0"),
        "node_latencies": {"classifier": Decimal("50.0"), "policy_checker": Decimal("100.0"), "decision_agent": Decimal("50.0")},
    },
    # 2026-10-02 - Damaged / Escalated
    {
        "refund_id": "ref_03",
        "created_at": "2026-10-02T10:15:00Z",
        "status": "escalated",
        "decision": "escalate",
        "category": "damaged",
        "confidence_score": Decimal("0.70"),
        "latency_ms": Decimal("150.0"),
        "node_latencies": {"classifier": Decimal("40.0"), "policy_checker": Decimal("60.0"), "decision_agent": Decimal("50.0")},
    },
    # 2026-10-05 - Late Delivery / Auto Approved
    {
        "refund_id": "ref_04",
        "created_at": "2026-10-05T12:00:00Z",
        "status": "completed",
        "decision": "auto_approve",
        "category": "late_delivery",
        "confidence_score": Decimal("0.95"),
        "latency_ms": Decimal("120.0"),
        "node_latencies": {"classifier": Decimal("35.0"), "policy_checker": Decimal("45.0"), "decision_agent": Decimal("40.0")},
    },
]


# ---------------------------------------------------------------------------
# Unit tests for repository get_analytics_category_breakdown
# ---------------------------------------------------------------------------

def test_get_analytics_category_breakdown_empty(repository_with_mock_table, mock_dynamo_table):
    """Empty table returns empty list of category breakdown."""
    mock_dynamo_table.scan.return_value = {"Items": []}
    cats = repository_with_mock_table.get_analytics_category_breakdown()
    assert cats == []


def test_get_analytics_category_breakdown_aggregation(repository_with_mock_table, mock_dynamo_table):
    """Aggregates requests by category with decision breakdowns."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    cats = repository_with_mock_table.get_analytics_category_breakdown()
    assert len(cats) == 3

    # Sorted by category name: damaged, late_delivery, wrong_item
    damaged = next(c for c in cats if c["category"] == "damaged")
    assert damaged["count"] == 2
    assert damaged["auto_approved"] == 1
    assert damaged["escalated"] == 1
    assert damaged["denied"] == 0

    wrong_item = next(c for c in cats if c["category"] == "wrong_item")
    assert wrong_item["count"] == 1
    assert wrong_item["auto_approved"] == 0
    assert wrong_item["escalated"] == 0
    assert wrong_item["denied"] == 1

    late_del = next(c for c in cats if c["category"] == "late_delivery")
    assert late_del["count"] == 1
    assert late_del["auto_approved"] == 1


def test_get_analytics_category_breakdown_with_date_filter(repository_with_mock_table, mock_dynamo_table):
    """Filters category breakdown by start_date and end_date."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    cats = repository_with_mock_table.get_analytics_category_breakdown(
        start_date="2026-10-01", end_date="2026-10-01"
    )
    assert len(cats) == 2
    cat_names = [c["category"] for c in cats]
    assert "damaged" in cat_names
    assert "wrong_item" in cat_names
    assert "late_delivery" not in cat_names


def test_get_analytics_category_breakdown_unclassified_fallback(repository_with_mock_table, mock_dynamo_table):
    """Items with missing or empty category map to 'unclassified'."""
    items = [
        {"refund_id": "r1", "created_at": "2026-10-01T00:00:00Z", "decision": "auto_approve"},
        {"refund_id": "r2", "created_at": "2026-10-01T00:00:00Z", "category": "", "decision": "deny"},
    ]
    mock_dynamo_table.scan.return_value = {"Items": items}
    cats = repository_with_mock_table.get_analytics_category_breakdown()
    assert len(cats) == 1
    assert cats[0]["category"] == "unclassified"
    assert cats[0]["count"] == 2
    assert cats[0]["auto_approved"] == 1
    assert cats[0]["denied"] == 1


# ---------------------------------------------------------------------------
# Unit tests for format helpers (_format_analytics_csv, _format_analytics_pdf)
# ---------------------------------------------------------------------------

def test_format_analytics_csv_structure():
    """CSV output contains all 4 required labeled sections and headers."""
    metrics = AnalyticsMetricsResponse(
        total_requests=4,
        auto_approval_rate=0.5,
        override_rate=0.0,
        average_confidence=0.8375,
        average_latency_ms=142.5,
        node_latency_breakdown={"classifier": 38.75, "policy_checker": 61.25, "decision_agent": 42.5},
    )
    trends = AnalyticsTrendsResponse(
        points=[
            TrendDataPoint(
                period="2026-10-01",
                total_requests=2,
                auto_approved=1,
                denied=1,
                escalated=0,
                average_confidence=0.85,
                average_latency_ms=150.0,
            )
        ]
    )
    categories = [
        {"category": "damaged", "count": 2, "auto_approved": 1, "escalated": 1, "denied": 0},
    ]

    csv_output = _format_analytics_csv(metrics, categories, trends)

    # Verify all 4 section titles
    assert "OVERALL KPIS" in csv_output
    assert "AGENT NODE LATENCY BREAKDOWN" in csv_output
    assert "CATEGORY BREAKDOWN" in csv_output
    assert "TIME-SERIES DAILY TRENDS" in csv_output

    # Verify KPI columns and values
    assert "Total Requests,Approval Rate,Override Rate,Escalation Rate,Denial Rate,Average Confidence,Average Latency (ms)" in csv_output
    assert "4,0.5000,0.0000,0.0000,0.0000,0.8375,142.50" in csv_output

    # Verify Node latencies
    assert "Classifier,38.75" in csv_output
    assert "Policy Checker,61.25" in csv_output
    assert "Decision Agent,42.50" in csv_output

    # Verify Category row
    assert "damaged,2,1,1,0" in csv_output

    # Verify Trend row
    assert "2026-10-01,2,1,1,0,0.8500,150.00" in csv_output


def test_format_analytics_pdf_validity():
    """PDF output starts with %PDF-1.4, ends with %%EOF, and contains required titles."""
    metrics = AnalyticsMetricsResponse(total_requests=0)
    trends = AnalyticsTrendsResponse(points=[])
    categories = []

    pdf_bytes = _format_analytics_pdf(metrics, categories, trends)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-1.4\n")
    assert pdf_bytes.strip().endswith(b"%%EOF")
    assert b"OPERATIONAL ANALYTICS REPORT" in pdf_bytes
    assert b"OVERALL KPIS" in pdf_bytes
    assert b"AGENT NODE LATENCY BREAKDOWN" in pdf_bytes
    assert b"CATEGORY BREAKDOWN" in pdf_bytes
    assert b"TIME-SERIES DAILY TRENDS" in pdf_bytes


# ---------------------------------------------------------------------------
# API Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_csv_success(client: AsyncClient, mock_dynamo_table):
    """GET /v1/analytics/export?format=csv returns 200 with text/csv and correct headers."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for endpoint in ("/v1/analytics/export?format=csv", "/analytics/export?format=csv"):
            response = await client.get(endpoint)
            assert response.status_code == 200
            assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
            assert response.headers["Content-Disposition"] == f'attachment; filename="analytics-report-{today_str}.csv"'

            content = response.text
            assert "OVERALL KPIS" in content
            assert "AGENT NODE LATENCY BREAKDOWN" in content
            assert "CATEGORY BREAKDOWN" in content
            assert "TIME-SERIES DAILY TRENDS" in content
            assert "damaged" in content
            assert "Classifier" in content
    finally:
        app.dependency_overrides.pop(get_repository, None)


@pytest.mark.asyncio
async def test_export_pdf_success(client: AsyncClient, mock_dynamo_table):
    """GET /v1/analytics/export?format=pdf returns 200 with application/pdf and valid PDF-1.4."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for endpoint in ("/v1/analytics/export?format=pdf", "/analytics/export?format=pdf"):
            response = await client.get(endpoint)
            assert response.status_code == 200
            assert response.headers["Content-Type"] == "application/pdf"
            assert response.headers["Content-Disposition"] == f'attachment; filename="analytics-report-{today_str}.pdf"'

            content = response.content
            assert content.startswith(b"%PDF-1.4\n")
            assert content.strip().endswith(b"%%EOF")
            assert len(content) > 200
    finally:
        app.dependency_overrides.pop(get_repository, None)


@pytest.mark.asyncio
async def test_export_with_date_range_filter(client: AsyncClient, mock_dynamo_table):
    """Export endpoints respect start_date and end_date filters."""
    mock_dynamo_table.scan.return_value = {"Items": SAMPLE_ITEMS}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        # Date range for 2026-10-01 only (2 requests)
        response = await client.get("/v1/analytics/export?format=csv&start_date=2026-10-01&end_date=2026-10-01")
        assert response.status_code == 200
        content = response.text
        assert "damaged,1,1,0,0" in content
        assert "wrong_item,1,0,0,1" in content
        assert "late_delivery" not in content
    finally:
        app.dependency_overrides.pop(get_repository, None)


@pytest.mark.asyncio
async def test_export_invalid_date_range_400(client: AsyncClient):
    """Export returns 400 Bad Request when start_date > end_date."""
    response = await client.get("/v1/analytics/export?format=csv&start_date=2026-10-10&end_date=2026-10-01")
    assert response.status_code == 400
    assert "start_date cannot be after end_date" in response.text


@pytest.mark.asyncio
async def test_export_invalid_format_422(client: AsyncClient):
    """Export returns 422 Unprocessable Entity when format is not csv or pdf."""
    response = await client.get("/v1/analytics/export?format=json")
    assert response.status_code == 422

    response_xlsx = await client.get("/v1/analytics/export?format=xlsx")
    assert response_xlsx.status_code == 422


@pytest.mark.asyncio
async def test_export_empty_table_returns_200(client: AsyncClient, mock_dynamo_table):
    """Export on empty table returns 200 with zeroed metrics for both CSV and PDF."""
    mock_dynamo_table.scan.return_value = {"Items": []}
    app.dependency_overrides[get_repository] = lambda: RefundRepository(
        dynamodb_resource=MagicMock(Table=lambda name: mock_dynamo_table), table_name="test_refunds"
    )

    try:
        # CSV export on empty table
        csv_resp = await client.get("/v1/analytics/export?format=csv")
        assert csv_resp.status_code == 200
        assert "OVERALL KPIS" in csv_resp.text
        assert "0,0.0000,0.0000,0.0000,0.0000,0.0000,0.00" in csv_resp.text

        # PDF export on empty table
        pdf_resp = await client.get("/v1/analytics/export?format=pdf")
        assert pdf_resp.status_code == 200
        assert pdf_resp.content.startswith(b"%PDF-1.4\n")
        assert pdf_resp.content.strip().endswith(b"%%EOF")
    finally:
        app.dependency_overrides.pop(get_repository, None)
