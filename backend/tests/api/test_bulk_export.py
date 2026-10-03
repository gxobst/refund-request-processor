"""Unit and integration tests for asynchronous bulk queue export endpoint."""

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from unittest.mock import MagicMock
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
    """In-memory mock repository for bulk export testing."""

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
async def test_post_bulk_export_job_returns_202(mock_repo: MockRefundRepository, local_storage: EvidenceStorageService):
    """Verify POST /v1/refunds/export/jobs returns 202 Accepted with job_id, created_at, expires_at."""
    mock_repo.seed_record(
        refund_id="ref_101",
        order_id="ORD-1001",
        status="completed",
        created_at="2026-10-01T10:00:00Z",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "csv", "status": "completed"},
        )

    assert response.status_code == 202
    data = response.json()
    assert data["job_id"].startswith("exp_")
    assert data["format"] == "csv"
    assert data["created_at"] is not None
    assert data["expires_at"] is not None
    assert data["status"] in ("pending", "processing", "completed")


@pytest.mark.asyncio
async def test_get_bulk_export_job_status_completed(mock_repo: MockRefundRepository, local_storage: EvidenceStorageService):
    """Verify GET /v1/refunds/export/jobs/{job_id} returns 200 with completed status and download_url."""
    mock_repo.seed_record(
        refund_id="ref_201",
        order_id="ORD-2001",
        status="pending",
        created_at="2026-10-01T10:00:00Z",
    )
    mock_repo.seed_record(
        refund_id="ref_202",
        order_id="ORD-2002",
        status="pending",
        created_at="2026-10-02T10:00:00Z",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create job
        create_res = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "csv", "status": "pending"},
        )
        assert create_res.status_code == 202
        job_id = create_res.json()["job_id"]

        # Fetch status
        status_res = await client.get(f"/v1/refunds/export/jobs/{job_id}")
        assert status_res.status_code == 200
        job_data = status_res.json()
        assert job_data["job_id"] == job_id
        assert job_data["status"] == "completed"
        assert job_data["record_count"] == 2
        assert job_data["download_url"] == f"/v1/refunds/export/jobs/{job_id}/download"
        assert job_data["completed_at"] is not None


@pytest.mark.asyncio
async def test_s3_presigned_url_generation(mock_repo: MockRefundRepository):
    """Verify S3 presigned URL generation with mocked boto3 S3 client."""
    mock_s3 = MagicMock()
    presigned_mock_url = "https://my-bucket.s3.amazonaws.com/exports/test.csv?signature=abc"
    mock_s3.generate_presigned_url.return_value = presigned_mock_url

    s3_storage = EvidenceStorageService(
        s3_client=mock_s3,
        bucket_name="my-test-bucket",
        storage_backend="s3",
    )
    app.dependency_overrides[get_evidence_storage_service] = lambda: s3_storage

    mock_repo.seed_record(
        refund_id="ref_s3_01",
        order_id="ORD-S3-01",
        status="completed",
        created_at="2026-10-01T12:00:00Z",
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_res = await client.post(
                "/v1/refunds/export/jobs",
                json={"format": "csv", "status": "completed"},
            )
            assert create_res.status_code == 202
            job_id = create_res.json()["job_id"]

            status_res = await client.get(f"/v1/refunds/export/jobs/{job_id}")
            assert status_res.status_code == 200
            job_data = status_res.json()
            assert job_data["status"] == "completed"
            assert job_data["download_url"] == presigned_mock_url

            # Verify generate_presigned_url was called with correct parameters
            mock_s3.generate_presigned_url.assert_called_with(
                "get_object",
                Params={"Bucket": "my-test-bucket", "Key": f"exports/{job_id}.csv"},
                ExpiresIn=3600,
            )

            # Test redirection when calling download endpoint with S3 presigned URL
            dl_res = await client.get(
                f"/v1/refunds/export/jobs/{job_id}/download",
                follow_redirects=False,
            )
            assert dl_res.status_code == 307
            assert dl_res.headers["location"] == presigned_mock_url
    finally:
        app.dependency_overrides.pop(get_evidence_storage_service, None)


@pytest.mark.asyncio
async def test_local_filesystem_fallback_download(mock_repo: MockRefundRepository, local_storage: EvidenceStorageService):
    """Verify local filesystem fallback creates export file and download endpoint returns 200."""
    mock_repo.seed_record(
        refund_id="ref_local_01",
        order_id="ORD-LOC-01",
        status="completed",
        decision="auto_approve",
        category="damaged",
        confidence_score=0.92,
        customer_request_text="Damaged screen",
        reasoning="Eligible for refund",
        created_at="2026-10-01T10:00:00Z",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test CSV local download
        create_res = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "csv"},
        )
        assert create_res.status_code == 202
        job_id_csv = create_res.json()["job_id"]

        dl_res_csv = await client.get(f"/v1/refunds/export/jobs/{job_id_csv}/download")
        assert dl_res_csv.status_code == 200
        assert "text/csv; charset=utf-8" in dl_res_csv.headers["content-type"]
        assert f'attachment; filename="refunds-export-{job_id_csv}.csv"' in dl_res_csv.headers["content-disposition"]

        csv_reader = list(csv.reader(io.StringIO(dl_res_csv.text)))
        assert len(csv_reader) == 2  # header + 1 record
        assert "Refund ID" in csv_reader[0]
        assert csv_reader[1][0] == "ref_local_01"

        # 2. Test JSON local download
        create_json_res = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "json"},
        )
        assert create_json_res.status_code == 202
        job_id_json = create_json_res.json()["job_id"]

        dl_res_json = await client.get(f"/v1/refunds/export/jobs/{job_id_json}/download")
        assert dl_res_json.status_code == 200
        assert "application/json" in dl_res_json.headers["content-type"]
        assert f'attachment; filename="refunds-export-{job_id_json}.json"' in dl_res_json.headers["content-disposition"]

        json_data = dl_res_json.json()
        assert len(json_data) == 1
        assert json_data[0]["refund_id"] == "ref_local_01"


@pytest.mark.asyncio
async def test_get_nonexistent_job_returns_404_problem_details(local_storage: EvidenceStorageService):
    """Verify HTTP 404 ProblemDetails when querying nonexistent job_id."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check GET status endpoint
        res = await client.get("/v1/refunds/export/jobs/exp_nonexistent_999")
        assert res.status_code == 404
        assert "application/problem+json" in res.headers.get("content-type", "")
        problem = res.json()
        assert problem["type"] == "urn:problem:not-found"
        assert problem["status"] == 404
        assert "exp_nonexistent_999" in problem["detail"]

        # Check GET download endpoint
        dl_res = await client.get("/v1/refunds/export/jobs/exp_nonexistent_999/download")
        assert dl_res.status_code == 404
        assert "application/problem+json" in dl_res.headers.get("content-type", "")
        problem_dl = dl_res.json()
        assert problem_dl["type"] == "urn:problem:not-found"
        assert problem_dl["status"] == 404


@pytest.mark.asyncio
async def test_post_bulk_export_start_date_greater_than_end_date_400():
    """Verify HTTP 400 Bad Request ProblemDetails when start_date > end_date."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/refunds/export/jobs",
            json={
                "format": "csv",
                "start_date": "2026-10-15",
                "end_date": "2026-10-01",
            },
        )
        assert res.status_code == 400
        assert "application/problem+json" in res.headers.get("content-type", "")
        problem = res.json()
        assert problem["type"] == "urn:problem:bad-request"
        assert problem["status"] == 400
        assert "cannot be after end_date" in problem["detail"]


@pytest.mark.asyncio
async def test_post_bulk_export_invalid_format_422():
    """Verify HTTP 422 Unprocessable Entity when format is invalid."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "xml"},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_empty_queue_bulk_export_completes_successfully(mock_repo: MockRefundRepository, local_storage: EvidenceStorageService):
    """Verify export of empty queue completes with status completed and record_count=0."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # CSV empty export
        res_csv = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "csv"},
        )
        assert res_csv.status_code == 202
        job_id_csv = res_csv.json()["job_id"]

        status_res = await client.get(f"/v1/refunds/export/jobs/{job_id_csv}")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "completed"
        assert status_res.json()["record_count"] == 0

        dl_csv = await client.get(f"/v1/refunds/export/jobs/{job_id_csv}/download")
        assert dl_csv.status_code == 200
        csv_rows = list(csv.reader(io.StringIO(dl_csv.text)))
        assert len(csv_rows) == 1  # Only headers
        assert "Refund ID" in csv_rows[0]

        # JSON empty export
        res_json = await client.post(
            "/v1/refunds/export/jobs",
            json={"format": "json"},
        )
        assert res_json.status_code == 202
        job_id_json = res_json.json()["job_id"]

        dl_json = await client.get(f"/v1/refunds/export/jobs/{job_id_json}/download")
        assert dl_json.status_code == 200
        assert dl_json.json() == []


@pytest.mark.asyncio
async def test_date_range_filtering(mock_repo: MockRefundRepository, local_storage: EvidenceStorageService):
    """Verify records are filtered by start_date and end_date correctly."""
    mock_repo.seed_record(
        refund_id="ref_sep_30",
        order_id="ORD-1",
        status="completed",
        created_at="2026-09-30T23:59:59Z",
    )
    mock_repo.seed_record(
        refund_id="ref_oct_01",
        order_id="ORD-2",
        status="completed",
        created_at="2026-10-01T12:00:00Z",
    )
    mock_repo.seed_record(
        refund_id="ref_oct_02",
        order_id="ORD-3",
        status="completed",
        created_at="2026-10-02T15:00:00Z",
    )
    mock_repo.seed_record(
        refund_id="ref_oct_05",
        order_id="ORD-4",
        status="completed",
        created_at="2026-10-05T00:00:01Z",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/refunds/export/jobs",
            json={
                "format": "json",
                "start_date": "2026-10-01",
                "end_date": "2026-10-02",
            },
        )
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        dl_res = await client.get(f"/v1/refunds/export/jobs/{job_id}/download")
        assert dl_res.status_code == 200
        exported = dl_res.json()
        exported_ids = {r["refund_id"] for r in exported}
        assert exported_ids == {"ref_oct_01", "ref_oct_02"}


@pytest.mark.asyncio
async def test_process_export_job_error_handling(mock_repo: MockRefundRepository):
    """Verify unexpected processing error transitions job status to failed."""
    failing_storage = MagicMock()
    failing_storage.save_export_file.side_effect = RuntimeError("Disk quota exceeded")

    job_req = BulkExportJobRequest(format="csv")
    job_id = "exp_fail_test"

    from app.api.refunds import _export_jobs
    _export_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "format": "csv",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": None,
        "completed_at": None,
        "download_url": None,
        "record_count": None,
        "error": None,
    }

    await process_export_job(job_id, job_req, mock_repo, failing_storage)

    assert _export_jobs[job_id]["status"] == "failed"
    assert "Disk quota exceeded" in _export_jobs[job_id]["error"]
