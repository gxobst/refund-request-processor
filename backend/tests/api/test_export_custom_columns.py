"""Unit and integration tests for customizable queue export column selection and ordering."""

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import (
    get_repository,
    reset_export_jobs,
    process_export_job,
)
from app.main import app
from app.schemas.refund import BulkExportJobRequest, RefundRecord
from app.services.storage import EvidenceStorageService, get_evidence_storage_service


class MockRefundRepository:
    """In-memory mock repository for custom columns export testing."""

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
        self, status: str | None = None, limit: int = 100000
    ) -> list[RefundRecord]:
        records = list(self.records.values())
        if status is not None:
            records = [r for r in records if r.status.lower() == status.strip().lower()]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]


@pytest.fixture(autouse=True)
def clean_export_state():
    reset_export_jobs()
    yield
    reset_export_jobs()


@pytest.fixture
def mock_repo() -> MockRefundRepository:
    repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_repository, None)


@pytest.fixture
def local_storage(tmp_path: Path) -> EvidenceStorageService:
    service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    app.dependency_overrides[get_evidence_storage_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_evidence_storage_service, None)


@pytest.mark.asyncio
async def test_sync_csv_export_custom_columns_comma_separated(mock_repo: MockRefundRepository):
    """Verify synchronous GET /v1/refunds/export?columns=refund_id,order_id outputs only those columns in order."""
    mock_repo.seed_record(refund_id="ref_001", order_id="ORD-1001", status="completed", created_at="2026-10-01T10:00:00Z")
    mock_repo.seed_record(refund_id="ref_002", order_id="ORD-1002", status="pending", created_at="2026-10-02T10:00:00Z")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/refunds/export?columns=refund_id,order_id")

    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]

    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    assert len(rows) == 3  # Header + 2 data rows
    assert rows[0] == ["Refund ID", "Order ID"]
    assert rows[1] == ["ref_002", "ORD-1002"]
    assert rows[2] == ["ref_001", "ORD-1001"]


@pytest.mark.asyncio
async def test_sync_csv_export_custom_columns_repeated_params(mock_repo: MockRefundRepository):
    """Verify synchronous GET /v1/refunds/export?columns=status&columns=refund_id outputs requested columns."""
    mock_repo.seed_record(refund_id="ref_001", order_id="ORD-1001", status="completed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/refunds/export?columns=status&columns=refund_id")

    assert resp.status_code == 200
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    assert rows[0] == ["Status", "Refund ID"]
    assert rows[1] == ["completed", "ref_001"]


@pytest.mark.asyncio
async def test_sync_csv_export_custom_columns_by_display_header_names(mock_repo: MockRefundRepository):
    """Verify synchronous export accepts display header names case-insensitively."""
    mock_repo.seed_record(refund_id="ref_001", order_id="ORD-1001", status="completed", decision="auto_approve")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/refunds/export?columns=Refund ID,Decision,Status")

    assert resp.status_code == 200
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    assert rows[0] == ["Refund ID", "Decision", "Status"]
    assert rows[1] == ["ref_001", "auto_approve", "completed"]


@pytest.mark.asyncio
async def test_sync_json_export_custom_columns(mock_repo: MockRefundRepository):
    """Verify synchronous GET /v1/refunds/export?format=json&columns=refund_id,status returns only requested keys."""
    mock_repo.seed_record(refund_id="ref_001", order_id="ORD-1001", status="completed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/refunds/export?format=json&columns=refund_id,status")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert list(data[0].keys()) == ["refund_id", "status"]
    assert data[0]["refund_id"] == "ref_001"
    assert data[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_sync_export_invalid_column_returns_400():
    """Verify GET /v1/refunds/export?columns=invalid_col returns HTTP 400 Bad Request with RFC 9457 ProblemDetails."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/refunds/export?columns=invalid_col")

    assert resp.status_code == 400
    data = resp.json()
    assert data["type"] == "urn:problem:bad-request"
    assert data["status"] == 400
    assert data["title"] == "Bad Request"
    assert "Invalid column(s): invalid_col" in data["detail"]


@pytest.mark.asyncio
async def test_sync_export_empty_columns_returns_400():
    """Verify GET /v1/refunds/export?columns= returns HTTP 400 Bad Request with RFC 9457 ProblemDetails."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/refunds/export?columns=")

    assert resp.status_code == 400
    data = resp.json()
    assert data["type"] == "urn:problem:bad-request"
    assert data["status"] == 400
    assert data["title"] == "Bad Request"
    assert "At least one column must be selected" in data["detail"]


@pytest.mark.asyncio
async def test_async_bulk_export_job_with_custom_columns(
    mock_repo: MockRefundRepository, local_storage: EvidenceStorageService
):
    """Verify asynchronous POST /v1/refunds/export/jobs with custom columns completes and generates filtered file."""
    mock_repo.seed_record(refund_id="ref_001", order_id="ORD-1001", status="completed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Initiate job with custom columns
        create_resp = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "csv", "columns": ["order_id", "status"]},
        )
        assert create_resp.status_code == 202
        job_id = create_resp.json()["job_id"]

        # 2. Process job directly
        req = BulkExportJobRequest(format="csv", columns=["order_id", "status"])
        await process_export_job(job_id=job_id, request_data=req, repo=mock_repo, storage=local_storage)

        # 3. Check job completed
        status_resp = await client.get(f"/v1/refunds/export/jobs/{job_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "completed"

        # 4. Download file and check columns
        download_resp = await client.get(f"/v1/refunds/export/jobs/{job_id}/download")
        assert download_resp.status_code == 200
        reader = csv.reader(io.StringIO(download_resp.text))
        rows = list(reader)
        assert rows[0] == ["Order ID", "Status"]
        assert rows[1] == ["ORD-1001", "completed"]


@pytest.mark.asyncio
async def test_async_bulk_export_job_json_with_custom_columns(
    mock_repo: MockRefundRepository, local_storage: EvidenceStorageService
):
    """Verify asynchronous bulk export job with JSON format and custom columns."""
    mock_repo.seed_record(refund_id="ref_001", order_id="ORD-1001", status="completed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "json", "columns": ["refund_id", "order_id"]},
        )
        assert create_resp.status_code == 202
        job_id = create_resp.json()["job_id"]

        req = BulkExportJobRequest(format="json", columns=["refund_id", "order_id"])
        await process_export_job(job_id=job_id, request_data=req, repo=mock_repo, storage=local_storage)

        download_resp = await client.get(f"/v1/refunds/export/jobs/{job_id}/download")
        assert download_resp.status_code == 200
        data = download_resp.json()
        assert len(data) == 1
        assert list(data[0].keys()) == ["refund_id", "order_id"]
        assert data[0]["refund_id"] == "ref_001"
        assert data[0]["order_id"] == "ORD-1001"


@pytest.mark.asyncio
async def test_async_bulk_export_job_empty_columns_returns_400():
    """Verify asynchronous POST /v1/refunds/export/jobs returns HTTP 400 when columns is empty list."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "csv", "columns": []},
        )

    assert resp.status_code == 400
    data = resp.json()
    assert data["type"] == "urn:problem:bad-request"
    assert data["status"] == 400
    assert "At least one column must be selected" in data["detail"]


@pytest.mark.asyncio
async def test_async_bulk_export_job_invalid_columns_returns_400():
    """Verify asynchronous POST /v1/refunds/export/jobs returns HTTP 400 when columns has invalid column."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "csv", "columns": ["order_id", "nonexistent_field"]},
        )

    assert resp.status_code == 400
    data = resp.json()
    assert data["type"] == "urn:problem:bad-request"
    assert data["status"] == 400
    assert "Invalid column(s): nonexistent_field" in data["detail"]
