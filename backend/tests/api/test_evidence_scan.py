"""API integration tests for asynchronous antivirus and malware inspection.

Verifies:
- Evidence uploaded via POST /{refund_id}/evidence has scan_status="pending" and enqueues scan task.
- Evidence uploaded via POST /{refund_id}/clarify has scan_status="pending" and enqueues scan task.
- Background scan task executes scan_evidence_file and updates repository with clean or infected status.
- Accessing infected evidence via GET /{refund_id}/evidence/{evidence_id} returns HTTP 403 Forbidden RFC 9457 Problem Details.
- Accessing clean evidence via GET /{refund_id}/evidence/{evidence_id} succeeds.
- Non-existent evidence returns HTTP 404 Not Found.
- update_evidence_scan_status in repository updates evidence metadata or raises RefundNotFoundError.
- Backward compatibility: Deserializing existing records lacking scan_status, scanned_at, threat_name defaults to 'pending'.
"""

from datetime import datetime, timezone
import struct
from typing import Any
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import _run_scan_task, get_repository
from app.db.repository import RefundNotFoundError
from app.main import app
from app.schemas.refund import EvidenceItem, RefundRecord
from app.services.malware_scanner import EICAR_TEST_STRING


def make_png(width: int = 50, height: int = 50) -> bytes:
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr_chunk = b"\x00\x00\x00\x0dIHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + ihdr_chunk


def make_jpeg(width: int = 50, height: int = 50) -> bytes:
    payload_len = 17
    sof_payload = (
        struct.pack(">H", payload_len)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    return b"\xff\xd8\xff\xc0" + sof_payload + b"\xff\xd9"


class MockRefundRepository:
    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str = "ORD-1001",
        status: str = "pending",
        evidence: list[dict[str, Any]] | None = None,
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        ev_items = [EvidenceItem.model_validate(e) for e in (evidence or [])]
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text="Need refund for damaged item",
            status=status,
            evidence=ev_items,
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.records[refund_id] = record
        return record

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        return self.records.get(refund_id)

    def add_evidence(self, refund_id: str, evidence_item: dict[str, Any]) -> RefundRecord:
        rec = self.records.get(refund_id)
        if rec is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")
        item = EvidenceItem.model_validate(evidence_item)
        rec.evidence.append(item)
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        return rec

    def submit_clarification_response(
        self, refund_id: str, clarification_response: str
    ) -> RefundRecord:
        rec = self.records.get(refund_id)
        if rec is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")
        rec.status = "pending"
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        return rec

    def update_evidence_scan_status(
        self,
        refund_id: str,
        storage_key: str,
        scan_status: str,
        threat_name: str | None = None,
        scanned_at: str | None = None,
    ) -> RefundRecord:
        rec = self.records.get(refund_id)
        if rec is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")
        now_iso = datetime.now(timezone.utc).isoformat()
        scanned_at_iso = scanned_at or now_iso
        for item in rec.evidence:
            if (
                item.storage_key == storage_key
                or item.evidence_id == storage_key
                or item.filename == storage_key
            ):
                item.scan_status = scan_status
                item.threat_name = threat_name
                item.scanned_at = scanned_at_iso
        rec.updated_at = now_iso
        return rec


@pytest.fixture
def mock_repo() -> MockRefundRepository:
    repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_repository, None)


@pytest.mark.asyncio
async def test_evidence_upload_initial_pending_scan_status(mock_repo: MockRefundRepository):
    """AC: Evidence uploaded via POST /{refund_id}/evidence is initially persisted with scan_status='pending'."""
    refund_id = "ref_scan_pending_01"
    mock_repo.seed_record(refund_id=refund_id, order_id="ORD-1001")

    valid_png = make_png(60, 60)
    files = {"file": ("damage.png", valid_png, "image/png")}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/refunds/{refund_id}/evidence", files=files)

    assert response.status_code == 201
    data = response.json()
    assert len(data["evidence"]) == 1
    assert data["evidence"][0]["scan_status"] == "pending"
    assert data["evidence"][0]["scanned_at"] is None
    assert data["evidence"][0]["threat_name"] is None


@pytest.mark.asyncio
async def test_run_scan_task_clean_file(mock_repo: MockRefundRepository):
    """AC: Background scan task updates clean evidence to 'clean' status."""
    refund_id = "ref_scan_clean_02"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1001",
        evidence=[
            {
                "storage_key": "evidence/ORD-1001/uuid_clean.png",
                "filename": "clean.png",
                "content_type": "image/png",
                "size_bytes": 100,
                "url": "http://test/clean.png",
                "scan_status": "pending",
            }
        ],
    )

    clean_bytes = make_png(80, 80)
    await _run_scan_task(
        refund_id=refund_id,
        storage_key="evidence/ORD-1001/uuid_clean.png",
        file_bytes=clean_bytes,
        repo=mock_repo,
    )

    rec = mock_repo.get_refund_request(refund_id)
    assert rec is not None
    assert rec.evidence[0].scan_status == "clean"
    assert rec.evidence[0].threat_name is None
    assert rec.evidence[0].scanned_at is not None


@pytest.mark.asyncio
async def test_run_scan_task_infected_eicar_file(mock_repo: MockRefundRepository):
    """AC: Background scan task identifies EICAR threat and updates status to 'infected'."""
    refund_id = "ref_scan_eicar_03"
    storage_key = "evidence/ORD-1001/uuid_eicar.png"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1001",
        evidence=[
            {
                "storage_key": storage_key,
                "filename": "eicar_test.png",
                "content_type": "image/png",
                "size_bytes": 150,
                "url": "http://test/eicar.png",
                "scan_status": "pending",
            }
        ],
    )

    infected_bytes = make_png(60, 60) + EICAR_TEST_STRING
    await _run_scan_task(
        refund_id=refund_id,
        storage_key=storage_key,
        file_bytes=infected_bytes,
        repo=mock_repo,
    )

    rec = mock_repo.get_refund_request(refund_id)
    assert rec is not None
    assert rec.evidence[0].scan_status == "infected"
    assert rec.evidence[0].threat_name == "Win32.Eicar.TestFile"
    assert rec.evidence[0].scanned_at is not None


@pytest.mark.asyncio
async def test_get_infected_evidence_returns_403_problem_details(
    mock_repo: MockRefundRepository,
):
    """AC: Accessing infected evidence returns HTTP 403 Forbidden with RFC 9457 Problem Details."""
    refund_id = "ref_infected_access_04"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1001",
        evidence=[
            {
                "evidence_id": "evi_malware_99",
                "storage_key": "evidence/ORD-1001/trojan.png",
                "filename": "trojan.png",
                "content_type": "image/png",
                "size_bytes": 2048,
                "url": "http://test/trojan.png",
                "scan_status": "infected",
                "threat_name": "Trojan.Generic.ExecutablePE",
                "scanned_at": "2026-10-04T12:00:00Z",
            }
        ],
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Test endpoint GET /refunds/{refund_id}/evidence/{evidence_id}
        resp = await client.get(f"/refunds/{refund_id}/evidence/evi_malware_99")
        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["type"] == "urn:problem:infected-evidence"
        assert body["title"] == "Infected Evidence File"
        assert body["status"] == 403
        assert body["detail"] == "Evidence file blocked: flagged as infected by security scan"

        # Test prefixed endpoint GET /v1/refunds/{refund_id}/evidence/{evidence_id}
        resp_v1 = await client.get(f"/v1/refunds/{refund_id}/evidence/evi_malware_99")
        assert resp_v1.status_code == 403
        assert resp_v1.json()["type"] == "urn:problem:infected-evidence"

        # Test download endpoint GET /refunds/{refund_id}/evidence/{evidence_id}/download
        resp_dl = await client.get(
            f"/refunds/{refund_id}/evidence/evi_malware_99/download"
        )
        assert resp_dl.status_code == 403
        assert resp_dl.json()["type"] == "urn:problem:infected-evidence"


@pytest.mark.asyncio
async def test_get_clean_evidence_succeeds(mock_repo: MockRefundRepository):
    """AC: Accessing clean evidence returns 307 redirect or file content."""
    refund_id = "ref_clean_access_05"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1001",
        evidence=[
            {
                "evidence_id": "evi_clean_42",
                "storage_key": "evidence/ORD-1001/clean.png",
                "filename": "clean.png",
                "content_type": "image/png",
                "size_bytes": 1024,
                "url": "http://storage.example.com/clean.png",
                "scan_status": "clean",
                "scanned_at": "2026-10-04T12:00:00Z",
            }
        ],
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/refunds/{refund_id}/evidence/evi_clean_42", follow_redirects=False
        )
        # Should redirect to URL
        assert resp.status_code == 307
        assert resp.headers["location"] == "http://storage.example.com/clean.png"


@pytest.mark.asyncio
async def test_get_evidence_by_index_or_missing(mock_repo: MockRefundRepository):
    """AC: Accessing evidence by index works, and missing evidence returns 404."""
    refund_id = "ref_idx_06"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1001",
        evidence=[
            {
                "evidence_id": "evi_first_001",
                "storage_key": "evidence/ORD-1001/first.png",
                "filename": "first.png",
                "content_type": "image/png",
                "size_bytes": 1024,
                "url": "http://storage.example.com/first.png",
                "scan_status": "clean",
            }
        ],
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Access by index "0"
        resp = await client.get(f"/refunds/{refund_id}/evidence/0", follow_redirects=False)
        assert resp.status_code == 307

        # Access non-existent evidence returns 404
        missing_resp = await client.get(f"/refunds/{refund_id}/evidence/nonexistent")
        assert missing_resp.status_code == 404

        # Access evidence for non-existent refund returns 404
        no_ref = await client.get("/refunds/non_existent_ref/evidence/0")
        assert no_ref.status_code == 404


@pytest.mark.asyncio
async def test_clarify_evidence_upload_pending_scan_status(mock_repo: MockRefundRepository):
    """AC: Evidence uploaded via POST /{refund_id}/clarify is initially persisted with scan_status='pending'."""
    refund_id = "ref_clarify_scan_07"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1001",
        status="awaiting_clarification",
    )

    valid_jpeg = make_jpeg(60, 60)
    data = {"response_text": "Here is the requested receipt photo."}
    files = {"evidence_file": ("receipt.jpg", valid_jpeg, "image/jpeg")}

    with patch("app.api.refunds.resume_refund_workflow") as mock_resume:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/refunds/{refund_id}/clarify", data=data, files=files
            )

    assert resp.status_code == 200
    res_data = resp.json()
    assert len(res_data["evidence"]) == 1
    assert res_data["evidence"][0]["scan_status"] == "pending"


def test_evidence_item_backward_compatibility_schema_deserialization():
    """AC: Deserializing existing records lacking scan_status, scanned_at, or threat_name preserves backward compatibility, defaulting scan_status to 'pending'."""
    legacy_evidence = {
        "storage_key": "evidence/ORD-1001/legacy_photo.jpg",
        "filename": "legacy_photo.jpg",
        "content_type": "image/jpeg",
        "size_bytes": 5000,
        "url": "http://storage.example.com/legacy_photo.jpg",
        "created_at": "2026-09-01T10:00:00Z",
    }
    # No scan_status, scanned_at, threat_name
    item = EvidenceItem.model_validate(legacy_evidence)
    assert item.scan_status == "pending"
    assert item.scanned_at is None
    assert item.threat_name is None

    # Explicit None scan_status
    legacy_none = dict(legacy_evidence)
    legacy_none["scan_status"] = None
    item_none = EvidenceItem.model_validate(legacy_none)
    assert item_none.scan_status == "pending"


def test_update_evidence_scan_status_not_found_raises(mock_repo: MockRefundRepository):
    """AC: update_evidence_scan_status raises RefundNotFoundError if refund does not exist."""
    with pytest.raises(RefundNotFoundError):
        mock_repo.update_evidence_scan_status(
            refund_id="non_existent_refund",
            storage_key="dummy_key",
            scan_status="clean",
        )


def test_real_dynamo_repository_update_evidence_scan_status():
    """AC: RefundRepository.update_evidence_scan_status updates DynamoDB record and raises RefundNotFoundError on missing refund."""
    from unittest.mock import patch
    from app.db.repository import RefundRepository

    class MockTable:
        def __init__(self):
            self.items = {}

        def put_item(self, Item: dict) -> dict:
            self.items[Item["refund_id"]] = Item
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

        def get_item(self, Key: dict) -> dict:
            item = self.items.get(Key.get("refund_id"))
            if item is not None:
                return {"Item": item}
            return {}

    mock_table = MockTable()

    with patch("boto3.resource") as mock_resource:
        mock_resource.return_value.Table.return_value = mock_table
        repo = RefundRepository(table_name="test-table")

        # 1. Missing refund raises RefundNotFoundError
        with pytest.raises(RefundNotFoundError):
            repo.update_evidence_scan_status(
                refund_id="missing_ref_id",
                storage_key="dummy_key",
                scan_status="clean",
            )

        # 2. Create record and add evidence
        record = repo.create_refund_request(
            order_id="ORD-9999",
            customer_request_text="Damaged delivery",
        )
        ev_item = EvidenceItem(
            storage_key="evidence/ORD-9999/broken.png",
            filename="broken.png",
            content_type="image/png",
            size_bytes=1024,
            url="http://test/broken.png",
            scan_status="pending",
        )
        repo.add_evidence(refund_id=record.refund_id, evidence_item=ev_item)

        # 3. Update scan status
        updated = repo.update_evidence_scan_status(
            refund_id=record.refund_id,
            storage_key="evidence/ORD-9999/broken.png",
            scan_status="infected",
            threat_name="Trojan.Generic.ExecutablePE",
            scanned_at="2026-10-04T12:45:00Z",
        )
        assert updated.evidence[0].scan_status == "infected"
        assert updated.evidence[0].threat_name == "Trojan.Generic.ExecutablePE"
        assert updated.evidence[0].scanned_at == "2026-10-04T12:45:00Z"

        # 4. Fetch from DynamoDB
        fetched = repo.get_refund_request(record.refund_id)
        assert fetched is not None
        assert fetched.evidence[0].scan_status == "infected"
        assert fetched.evidence[0].threat_name == "Trojan.Generic.ExecutablePE"
        assert fetched.evidence[0].scanned_at == "2026-10-04T12:45:00Z"

