"""Unit and integration tests for refund queue CSV and JSON export endpoints."""

import csv
from datetime import datetime, timezone
import io
import json
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.main import app
from app.schemas.refund import RefundRecord


class MockRefundRepository:
    """In-memory mock repository for export testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str,
        status: str,
        created_at: str | None = None,
        updated_at: str | None = None,
        decision: str | None = None,
        reasoning: str | None = None,
        category: str | None = None,
        confidence_score: float | None = None,
        customer_request_text: str | None = None,
        override_decision: str | None = None,
        override_reason: str | None = None,
    ) -> RefundRecord:
        now_iso = created_at or datetime.now(timezone.utc).isoformat()
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text or f"Request for {order_id}",
            status=status,
            decision=decision,
            reasoning=reasoning,
            category=category,
            confidence_score=confidence_score,
            override_decision=override_decision,
            override_reason=override_reason,
            created_at=now_iso,
            updated_at=updated_at or now_iso,
        )
        self.records[refund_id] = record
        return record

    def list_refund_requests(
        self, status: str | None = None, limit: int = 10000
    ) -> list[RefundRecord]:
        records = list(self.records.values())
        if status is not None:
            records = [r for r in records if r.status.lower() == status.strip().lower()]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]


@pytest.fixture
def mock_repo() -> MockRefundRepository:
    repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_csv_headers_and_content(mock_repo: MockRefundRepository):
    """Verify GET /v1/refunds/export?format=csv returns RFC 4180 CSV with 13 standard columns."""
    mock_repo.seed_record(
        refund_id="ref_101",
        order_id="ORD-2001",
        status="completed",
        decision="auto_approve",
        category="damaged",
        confidence_score=0.95,
        customer_request_text="Screen arrived shattered",
        reasoning="Satisfies damaged item policy within 30 days",
        override_decision=None,
        override_reason=None,
        created_at="2026-10-01T10:00:00Z",
        updated_at="2026-10-01T10:05:00Z",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/refunds/export?format=csv")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=\"refunds-all-" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('.csv"')

    content = response.text
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    assert len(rows) == 2
    expected_headers = [
        "Refund ID",
        "Order ID",
        "Status",
        "Decision",
        "Category",
        "Refund Amount",
        "Confidence Score",
        "Customer Request",
        "Decision Reasoning",
        "Override Decision",
        "Override Reason",
        "Created At",
        "Updated At",
    ]
    assert rows[0] == expected_headers
    assert rows[1] == [
        "ref_101",
        "ORD-2001",
        "completed",
        "auto_approve",
        "damaged",
        "",
        "0.95",
        "Screen arrived shattered",
        "Satisfies damaged item policy within 30 days",
        "",
        "",
        "2026-10-01T10:00:00Z",
        "2026-10-01T10:05:00Z",
    ]


@pytest.mark.asyncio
async def test_export_csv_without_v1_prefix(mock_repo: MockRefundRepository):
    """Verify GET /refunds/export?format=csv works identically without the /v1 prefix."""
    mock_repo.seed_record("ref_102", "ORD-2002", "pending")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/refunds/export?format=csv")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=\"refunds-all-" in response.headers["content-disposition"]
    assert "ref_102" in response.text


@pytest.mark.asyncio
async def test_export_default_format_is_csv(mock_repo: MockRefundRepository):
    """Verify calling /v1/refunds/export without format defaults to CSV."""
    mock_repo.seed_record("ref_103", "ORD-2003", "pending")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/refunds/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "ref_103" in response.text


@pytest.mark.asyncio
async def test_export_json_format(mock_repo: MockRefundRepository):
    """Verify GET /v1/refunds/export?format=json returns formatted JSON array."""
    mock_repo.seed_record(
        refund_id="ref_201",
        order_id="ORD-3001",
        status="escalated",
        decision="escalate",
        category="late_delivery",
        confidence_score=0.6,
        customer_request_text="Package arrived two weeks late",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/refunds/export?format=json")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert "attachment; filename=\"refunds-all-" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('.json"')

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["refund_id"] == "ref_201"
    assert data[0]["order_id"] == "ORD-3001"
    assert data[0]["status"] == "escalated"


@pytest.mark.asyncio
async def test_export_json_without_v1_prefix(mock_repo: MockRefundRepository):
    """Verify GET /refunds/export?format=json works identically without /v1 prefix."""
    mock_repo.seed_record("ref_202", "ORD-3002", "completed")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/refunds/export?format=json")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert len(data) == 1
    assert data[0]["refund_id"] == "ref_202"


@pytest.mark.asyncio
async def test_export_status_filter_csv_and_json(mock_repo: MockRefundRepository):
    """Verify status query parameter filters records and reflects in the export filename."""
    mock_repo.seed_record("ref_pending_1", "ORD-1", "pending")
    mock_repo.seed_record("ref_pending_2", "ORD-2", "pending")
    mock_repo.seed_record("ref_completed_1", "ORD-3", "completed")
    mock_repo.seed_record("ref_escalated_1", "ORD-4", "escalated")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test pending CSV
        res_csv = await client.get("/v1/refunds/export?format=csv&status=pending")
        assert res_csv.status_code == 200
        assert "attachment; filename=\"refunds-pending-" in res_csv.headers["content-disposition"]
        csv_rows = list(csv.reader(io.StringIO(res_csv.text)))
        assert len(csv_rows) == 3  # header + 2 pending records
        assert "ref_pending_1" in res_csv.text
        assert "ref_pending_2" in res_csv.text
        assert "ref_completed_1" not in res_csv.text

        # Test escalated JSON
        res_json = await client.get("/v1/refunds/export?format=json&status=escalated")
        assert res_json.status_code == 200
        assert "attachment; filename=\"refunds-escalated-" in res_json.headers["content-disposition"]
        json_data = res_json.json()
        assert len(json_data) == 1
        assert json_data[0]["refund_id"] == "ref_escalated_1"


@pytest.mark.asyncio
async def test_export_rfc_4180_escaping(mock_repo: MockRefundRepository):
    """Verify fields containing commas, double quotes, and newlines are properly escaped."""
    mock_repo.seed_record(
        refund_id="ref_escape",
        order_id="ORD-9999",
        status="escalated",
        customer_request_text='The "super, fast" drone arrived damaged.\nMotor was smoking, blade broke.',
        reasoning='Policy check failed, ambiguous damage.\r\nEscalated to "supervisor" review.',
        override_decision="approve",
        override_reason='Manual override: verified customer video proof, signed "waiver".',
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/refunds/export?format=csv")

    assert response.status_code == 200
    reader = csv.reader(io.StringIO(response.text))
    rows = list(reader)
    assert len(rows) == 2

    data_row = rows[1]
    assert data_row[7] == 'The "super, fast" drone arrived damaged.\nMotor was smoking, blade broke.'
    assert data_row[8] == 'Policy check failed, ambiguous damage.\r\nEscalated to "supervisor" review.'
    assert data_row[10] == 'Manual override: verified customer video proof, signed "waiver".'


@pytest.mark.asyncio
async def test_export_empty_results(mock_repo: MockRefundRepository):
    """Verify empty queue returns header-only CSV or empty JSON array [] with HTTP 200."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Empty CSV
        res_csv = await client.get("/v1/refunds/export?format=csv")
        assert res_csv.status_code == 200
        assert res_csv.headers["content-type"] == "text/csv; charset=utf-8"
        rows = list(csv.reader(io.StringIO(res_csv.text)))
        assert len(rows) == 1  # Only header row
        assert rows[0][0] == "Refund ID"

        # Empty JSON
        res_json = await client.get("/v1/refunds/export?format=json")
        assert res_json.status_code == 200
        assert res_json.headers["content-type"] == "application/json"
        assert res_json.json() == []

        # Empty due to non-matching filter
        mock_repo.seed_record("ref_1", "ORD-1", "completed")
        res_filtered_csv = await client.get("/v1/refunds/export?format=csv&status=pending")
        assert res_filtered_csv.status_code == 200
        filtered_rows = list(csv.reader(io.StringIO(res_filtered_csv.text)))
        assert len(filtered_rows) == 1

        res_filtered_json = await client.get("/v1/refunds/export?format=json&status=pending")
        assert res_filtered_json.status_code == 200
        assert res_filtered_json.json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_format", ["xml", "pdf", "yaml", "html", ""])
async def test_export_invalid_format_returns_422(
    mock_repo: MockRefundRepository, invalid_format: str
):
    """Verify unsupported formats return HTTP 422 with RFC 9457 ProblemDetails."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test /v1/refunds/export
        res_v1 = await client.get(f"/v1/refunds/export?format={invalid_format}")
        assert res_v1.status_code == 422
        body = res_v1.json()
        assert "detail" in body

        # Test /refunds/export
        res = await client.get(f"/refunds/export?format={invalid_format}")
        assert res.status_code == 422
