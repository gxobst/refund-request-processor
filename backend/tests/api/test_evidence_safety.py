"""API integration tests for automated evidence image format and safety validation.

Verifies:
- Valid evidence upload returns 201 with enriched width, height, and format metadata.
- Spoofed file rejection returns HTTP 400 Bad Request with RFC 9457 ProblemDetails.
- Under-resolution rejection returns HTTP 400 Bad Request with RFC 9457 ProblemDetails.
- Over-resolution rejection returns HTTP 400 Bad Request with RFC 9457 ProblemDetails.
- Oversized file upload returns HTTP 413 Payload Too Large with RFC 9457 ProblemDetails.
- Clarify endpoint evidence upload validation failure returns HTTP 400 ProblemDetails.
- POST /refunds multipart initial evidence upload validation failure returns HTTP 400 ProblemDetails.
- Validation failures never persist to storage/repository and never trigger workflow resumption.
"""

from datetime import datetime, timezone
import struct
from typing import Any
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.main import app
from app.schemas.refund import EvidenceItem, RefundRecord


# --- Minimal Image Binary Generators ---


def make_png(width: int, height: int) -> bytes:
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr_chunk = b"\x00\x00\x00\x0dIHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + ihdr_chunk


def make_jpeg(width: int, height: int) -> bytes:
    payload_len = 17
    sof_payload = (
        struct.pack(">H", payload_len)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    return b"\xff\xd8\xff\xc0" + sof_payload + b"\xff\xd9"


def make_webp(width: int, height: int) -> bytes:
    packed = ((width - 1) & 0x3FFF) | (((height - 1) & 0x3FFF) << 14)
    vp8l_data = b"\x2f" + struct.pack("<I", packed)
    chunk = b"VP8L" + struct.pack("<I", len(vp8l_data)) + vp8l_data
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


class MockRefundRepository:
    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str = "ORD-8501",
        status: str = "pending",
        customer_request_text: str = "Test request for safety validation",
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text,
            status=status,
            evidence=[],
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.records[refund_id] = record
        return record

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        return self.records.get(refund_id)

    def add_evidence(
        self, refund_id: str, evidence_item: EvidenceItem | dict[str, Any]
    ) -> RefundRecord:
        record = self.records[refund_id]
        item = (
            evidence_item
            if isinstance(evidence_item, EvidenceItem)
            else EvidenceItem.model_validate(evidence_item)
        )
        updated = record.model_copy(
            update={
                "evidence": [*record.evidence, item],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.records[refund_id] = updated
        return updated

    def submit_clarification_response(
        self, refund_id: str, clarification_response: str
    ) -> RefundRecord:
        record = self.records[refund_id]
        updated = record.model_copy(
            update={
                "status": "pending",
                "clarification_response": clarification_response,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.records[refund_id] = updated
        return updated


@pytest.fixture
def mock_repo() -> MockRefundRepository:
    repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_repository, None)


# --- Tests for POST /refunds/{refund_id}/evidence ---


@pytest.mark.asyncio
async def test_upload_evidence_valid_image_enriches_metadata(mock_repo: MockRefundRepository):
    """Uploading a valid PNG returns 201 with width, height, and format enriched in evidence."""
    mock_repo.seed_record("ref-valid-01")
    png_bytes = make_png(640, 480)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/ref-valid-01/evidence",
            files={"file": ("photo.png", png_bytes, "image/png")},
        )

    assert response.status_code == 201
    data = response.json()
    assert len(data["evidence"]) == 1
    evi = data["evidence"][0]
    assert evi["width"] == 640
    assert evi["height"] == 480
    assert evi["format"] == "png"
    assert evi["filename"] == "photo.png"


@pytest.mark.asyncio
async def test_upload_evidence_spoofed_file_returns_problem_details_400(
    mock_repo: MockRefundRepository,
):
    """Uploading an HTML file pretending to be a JPG returns 400 RFC 9457 ProblemDetails."""
    mock_repo.seed_record("ref-spoofed-01")
    fake_jpg = b"<html><head><title>Phishing</title></head></html>"
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/refunds/ref-spoofed-01/evidence",
                files={"file": ("malicious.jpg", fake_jpg, "image/jpeg")},
            )

        assert response.status_code == 400
        assert "application/problem+json" in response.headers.get("content-type", "")
        problem = response.json()
        assert problem["type"] == "urn:problem:bad-request"
        assert problem["title"] == "Bad Request"
        assert problem["status"] == 400
        assert "File signature does not match allowed image formats" in problem["detail"]
        assert problem["instance"] == "/refunds/ref-spoofed-01/evidence"

        # Verify nothing persisted or enqueued
        record = mock_repo.get_refund_request("ref-spoofed-01")
        assert len(record.evidence) == 0
        mock_resume.assert_not_called()


@pytest.mark.asyncio
async def test_upload_evidence_under_resolution_returns_problem_details_400(
    mock_repo: MockRefundRepository,
):
    """Uploading an image below 50x50 returns 400 RFC 9457 ProblemDetails."""
    mock_repo.seed_record("ref-small-01")
    small_png = make_png(30, 40)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/ref-small-01/evidence",
            files={"file": ("small.png", small_png, "image/png")},
        )

    assert response.status_code == 400
    problem = response.json()
    assert problem["status"] == 400
    assert problem["title"] == "Bad Request"
    assert "below minimum required resolution of 50x50 pixels" in problem["detail"]
    assert "30x40" in problem["detail"]


@pytest.mark.asyncio
async def test_upload_evidence_over_resolution_returns_problem_details_400(
    mock_repo: MockRefundRepository,
):
    """Uploading an image exceeding 8192x8192 returns 400 RFC 9457 ProblemDetails."""
    mock_repo.seed_record("ref-huge-res-01")
    huge_res_png = make_png(9000, 100)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/ref-huge-res-01/evidence",
            files={"file": ("huge.png", huge_res_png, "image/png")},
        )

    assert response.status_code == 400
    problem = response.json()
    assert problem["status"] == 400
    assert problem["title"] == "Bad Request"
    assert "exceed maximum allowed resolution of 8192x8192 pixels" in problem["detail"]
    assert "9000x100" in problem["detail"]


@pytest.mark.asyncio
async def test_upload_evidence_oversized_file_returns_problem_details_413(
    mock_repo: MockRefundRepository,
):
    """Uploading a file exceeding 5MB returns 413 RFC 9457 ProblemDetails."""
    mock_repo.seed_record("ref-oversize-01")
    oversized = b"x" * (5 * 1024 * 1024 + 50)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/ref-oversize-01/evidence",
            files={"file": ("oversize.jpg", oversized, "image/jpeg")},
        )

    assert response.status_code == 413
    assert "application/problem+json" in response.headers.get("content-type", "")
    problem = response.json()
    assert problem["status"] == 413
    assert problem["title"] == "Payload Too Large"
    assert "exceeds maximum allowed limit" in problem["detail"]


# --- Tests for POST /refunds/{refund_id}/clarify with Evidence ---


@pytest.mark.asyncio
async def test_clarify_spoofed_evidence_returns_problem_details_400(mock_repo: MockRefundRepository):
    """Submitting clarification with spoofed evidence returns 400 ProblemDetails."""
    mock_repo.seed_record("ref-clarify-01", status="awaiting_clarification")
    spoofed = b"executable binary contents MZ\x90\x00"
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/refunds/ref-clarify-01/clarify",
                data={"response_text": "Here is the proof requested."},
                files={"evidence_file": ("proof.jpg", spoofed, "image/jpeg")},
            )

        assert response.status_code == 400
        problem = response.json()
        assert problem["type"] == "urn:problem:bad-request"
        assert problem["status"] == 400
        assert "File signature does not match allowed image formats" in problem["detail"]
        mock_resume.assert_not_called()


# --- Tests for POST /refunds Multipart Submission ---


@pytest.mark.asyncio
async def test_submit_refund_spoofed_initial_evidence_returns_problem_details_400(
    mock_repo: MockRefundRepository,
):
    """Initial refund submission with spoofed evidence returns 400 ProblemDetails."""
    spoofed = b"Plain text file not an image."
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.run_refund_workflow", new_callable=AsyncMock) as mock_run:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/refunds",
                data={"order_id": "ORD-8501", "customer_request_text": "Item damaged."},
                files={"file": ("proof.png", spoofed, "image/png")},
            )

        assert response.status_code == 400
        problem = response.json()
        assert problem["type"] == "urn:problem:bad-request"
        assert problem["status"] == 400
        assert "File signature does not match allowed image formats" in problem["detail"]
        mock_run.assert_not_called()
