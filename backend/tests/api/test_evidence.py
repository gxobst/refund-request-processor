"""API integration tests for multipart evidence upload endpoint (POST /refunds/{refund_id}/evidence)."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.db.repository import RefundNotFoundError
from app.main import app
from app.schemas.refund import ClarificationTurn, EvidenceItem, RefundRecord


class MockRefundRepository:
    """In-memory mock repository for evidence upload testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str = "ORD-1001",
        status: str = "pending",
        customer_request_text: str = "Damaged item received",
        clarification_history: list[ClarificationTurn] | list[dict[str, Any]] | None = None,
        clarification_prompt: str | None = None,
        clarification_response: str | None = None,
        clarification_count: int = 0,
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        turns: list[ClarificationTurn] = []
        if clarification_history:
            for turn in clarification_history:
                if isinstance(turn, ClarificationTurn):
                    turns.append(turn)
                else:
                    turns.append(ClarificationTurn.model_validate(turn))
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text,
            status=status,
            clarification_history=turns,
            clarification_prompt=clarification_prompt,
            clarification_response=clarification_response,
            clarification_count=clarification_count,
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.records[refund_id] = record
        return record

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        return self.records.get(refund_id)

    def submit_clarification_response(
        self, refund_id: str, clarification_response: str
    ) -> RefundRecord:
        record = self.records.get(refund_id)
        if record is None:
            raise RefundNotFoundError(f"Refund request '{refund_id}' not found.")
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_resp = clarification_response.strip()
        updated_history = [turn.model_copy() for turn in record.clarification_history]
        target_cycle = record.clarification_count or 1
        found = False
        for i in reversed(range(len(updated_history))):
            if updated_history[i].cycle == target_cycle:
                updated_history[i].response = clean_resp
                found = True
                break
        if not found:
            if updated_history:
                updated_history[-1].response = clean_resp
            else:
                updated_history.append(
                    ClarificationTurn(
                        cycle=target_cycle,
                        prompt=record.clarification_prompt,
                        response=clean_resp,
                        timestamp=now_iso,
                        evidence_ids=[],
                    )
                )

        updated = record.model_copy(
            update={
                "status": "pending",
                "clarification_response": clean_resp,
                "clarification_history": updated_history,
                "updated_at": now_iso,
            }
        )
        self.records[refund_id] = updated
        return updated

    def add_evidence(
        self, refund_id: str, evidence_item: EvidenceItem | dict[str, Any]
    ) -> RefundRecord:
        record = self.records.get(refund_id)
        if record is None:
            raise RefundNotFoundError(f"Refund request '{refund_id}' not found.")
        now_iso = datetime.now(timezone.utc).isoformat()
        if isinstance(evidence_item, dict):
            item = EvidenceItem.model_validate(evidence_item)
        else:
            item = evidence_item
        evidence_list = list(record.evidence)
        evidence_list.append(item)

        updated_history = [turn.model_copy(deep=True) for turn in record.clarification_history]
        if updated_history:
            if item.evidence_id not in updated_history[-1].evidence_ids:
                updated_history[-1].evidence_ids.append(item.evidence_id)

        updated = record.model_copy(
            update={
                "evidence": evidence_list,
                "clarification_history": updated_history,
                "updated_at": now_iso,
            }
        )
        self.records[refund_id] = updated
        return updated


from pathlib import Path
from app.services.storage import EvidenceStorageService, get_evidence_storage_service


@pytest.fixture
def mock_repo() -> MockRefundRepository:
    repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_storage(tmp_path: Path):
    service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    app.dependency_overrides[get_evidence_storage_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_evidence_storage_service, None)


@pytest.mark.asyncio
async def test_upload_evidence_success_201(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/evidence returns 201 and appends evidence item."""
    refund_id = "ref-evidence-1"
    mock_repo.seed_record(refund_id=refund_id, order_id="ORD-2001")
    transport = ASGITransport(app=app)

    file_bytes = b"fake-jpg-broken-screen"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("broken_screen.jpg", file_bytes, "image/jpeg")},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["refund_id"] == refund_id
    assert len(data["evidence"]) == 1

    item = data["evidence"][0]
    assert item["filename"] == "broken_screen.jpg"
    assert item["content_type"] == "image/jpeg"
    assert item["size_bytes"] == len(file_bytes)
    assert item["storage_key"].startswith("evidence/ORD-2001/")
    assert item["url"].startswith("/static/uploads/evidence/ORD-2001/")
    assert "evidence_id" in item
    assert "created_at" in item


@pytest.mark.asyncio
async def test_upload_evidence_multiple_sequential(mock_repo: MockRefundRepository):
    """Test sequential evidence uploads append multiple items to the refund record."""
    refund_id = "ref-evidence-seq"
    mock_repo.seed_record(refund_id=refund_id, order_id="ORD-2002")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First upload: photo of item
        res1 = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("item_photo.png", b"item-png-bytes", "image/png")},
        )
        assert res1.status_code == 201
        assert len(res1.json()["evidence"]) == 1

        # Second upload: packaging photo
        res2 = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("packaging.webp", b"webp-bytes", "image/webp")},
        )
        assert res2.status_code == 201
        assert len(res2.json()["evidence"]) == 2

    stored = mock_repo.get_refund_request(refund_id)
    assert stored is not None
    assert len(stored.evidence) == 2
    assert stored.evidence[0].filename == "item_photo.png"
    assert stored.evidence[1].filename == "packaging.webp"


@pytest.mark.asyncio
async def test_upload_evidence_not_found_404(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/evidence returns 404 for unknown refund_id."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/nonexistent-refund-id/evidence",
            files={"file": ("photo.jpg", b"bytes", "image/jpeg")},
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,content_type",
    [
        ("report.pdf", "application/pdf"),
        ("instructions.txt", "text/plain"),
        ("page.html", "text/html"),
        ("image.gif", "image/gif"),
    ],
)
async def test_upload_evidence_disallowed_mime_type_400(
    mock_repo: MockRefundRepository, filename: str, content_type: str
):
    """Test POST /refunds/{refund_id}/evidence returns 400 for disallowed MIME types."""
    refund_id = "ref-invalid-mime"
    mock_repo.seed_record(refund_id=refund_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": (filename, b"content", content_type)},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_evidence_disallowed_extension_400(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/evidence returns 400 for dangerous/disallowed file extensions."""
    refund_id = "ref-invalid-ext"
    mock_repo.seed_record(refund_id=refund_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("malware.exe", b"binary", "image/jpeg")},
        )

    assert response.status_code == 400
    assert "disallowed file extension" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_evidence_image_size_exceeded_413(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/evidence returns 413 when image exceeds 5MB limit."""
    refund_id = "ref-oversized-image"
    mock_repo.seed_record(refund_id=refund_id)
    transport = ASGITransport(app=app)

    oversized_bytes = b"x" * (5 * 1024 * 1024 + 1)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("huge_photo.jpg", oversized_bytes, "image/jpeg")},
        )

    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("video_filename,video_mime", [
    ("unboxing.mp4", "video/mp4"),
    ("damage_inspection.mov", "video/quicktime"),
])
async def test_upload_evidence_video_rejected_400(
    mock_repo: MockRefundRepository, video_filename: str, video_mime: str
):
    """API integration test: uploading .mp4 or .mov files to POST /refunds/{refund_id}/evidence returns HTTP 400."""
    refund_id = "ref-video-upload"
    mock_repo.seed_record(refund_id=refund_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": (video_filename, b"fake-video-bytes", video_mime)},
        )

    assert response.status_code == 400
    assert "disallowed file extension" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_evidence_openapi_schema():
    """Unit test fetches GET /openapi.json and asserts the OpenAPI spec for POST /refunds/{refund_id}/evidence defines multipart/form-data with binary format."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    endpoint = spec["paths"]["/refunds/{refund_id}/evidence"]["post"]
    assert "requestBody" in endpoint
    request_body = endpoint["requestBody"]
    assert request_body.get("required") is True
    content = request_body["content"]
    assert "multipart/form-data" in content

    schema = content["multipart/form-data"]["schema"]
    assert schema["type"] == "object"
    assert "file" in schema["properties"]
    assert schema["properties"]["file"]["type"] == "string"
    assert schema["properties"]["file"]["format"] == "binary"
    assert "file" in schema["required"]


@pytest.mark.asyncio
async def test_upload_evidence_mixed_case_webkit_boundary(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/evidence with mixed-case WebKit boundary successfully parses file, saves to storage, and returns HTTP 201."""
    refund_id = "ref-evidence-boundary"
    mock_repo.seed_record(refund_id=refund_id, order_id="ORD-2003")
    boundary = "----WebKitFormBoundaryAbCdEf123456"
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="screen.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["refund_id"] == refund_id
    assert len(data["evidence"]) == 1
    assert data["evidence"][0]["filename"] == "screen.png"
    assert data["evidence"][0]["content_type"] == "image/png"

    record = mock_repo.get_refund_request(refund_id)
    assert record is not None
    assert len(record.evidence) == 1
    assert record.evidence[0].filename == "screen.png"
    assert record.evidence[0].content_type == "image/png"


@pytest.mark.asyncio
async def test_upload_evidence_awaiting_clarification_queues_workflow_and_sets_pending(
    mock_repo: MockRefundRepository,
):
    """AC: Uploading evidence on status 'awaiting_clarification' queues resume_refund_workflow and transitions status to 'pending'."""
    refund_id = "ref-evidence-resume"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-3001",
        status="awaiting_clarification",
        customer_request_text="Damaged monitor on arrival",
    )
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/refunds/{refund_id}/evidence",
                files={"file": ("damaged_monitor.png", b"image-png-bytes", "image/png")},
            )

    assert response.status_code == 201
    data = response.json()
    assert data["refund_id"] == refund_id
    assert data["status"] == "pending"
    assert data["clarification_response"] == "Uploaded evidence file: damaged_monitor.png"
    assert len(data["evidence"]) == 1
    assert data["evidence"][0]["filename"] == "damaged_monitor.png"

    # Verify repository record
    stored = mock_repo.get_refund_request(refund_id)
    assert stored is not None
    assert stored.status == "pending"
    assert stored.clarification_response == "Uploaded evidence file: damaged_monitor.png"
    assert len(stored.evidence) == 1

    # Verify background task was queued with expected arguments
    mock_resume.assert_called_once()
    call_kwargs = mock_resume.call_args.kwargs
    assert call_kwargs["refund_id"] == refund_id
    assert call_kwargs["response_text"] == "Uploaded evidence file: damaged_monitor.png"
    assert len(call_kwargs["evidence"]) == 1
    assert call_kwargs["evidence"][0]["filename"] == "damaged_monitor.png"
    assert call_kwargs["repository"] == mock_repo


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", ["pending", "escalated"])
async def test_upload_evidence_non_awaiting_clarification_does_not_queue_workflow(
    mock_repo: MockRefundRepository, initial_status: str
):
    """AC: Uploading evidence on status other than 'awaiting_clarification' appends evidence but does NOT enqueue background task."""
    refund_id = f"ref-evidence-{initial_status}"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-3002",
        status=initial_status,
        customer_request_text="Customer refund request",
    )
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/refunds/{refund_id}/evidence",
                files={"file": ("extra_photo.jpg", b"jpeg-bytes", "image/jpeg")},
            )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == initial_status
    assert len(data["evidence"]) == 1
    assert data["evidence"][0]["filename"] == "extra_photo.jpg"

    # Verify background task was NOT queued
    mock_resume.assert_not_called()

    # Verify repo state
    stored = mock_repo.get_refund_request(refund_id)
    assert stored is not None
    assert stored.status == initial_status
    assert len(stored.evidence) == 1


@pytest.mark.asyncio
async def test_upload_evidence_validation_failures_never_enqueue_background_task(
    mock_repo: MockRefundRepository,
):
    """AC: Validation failures (404, 400 disallowed ext, 413 oversized) never enqueue background tasks."""
    refund_id = "ref-evidence-val"
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-3003",
        status="awaiting_clarification",
    )
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. 404 Not Found (non-existent refund_id)
            res_404 = await client.post(
                "/refunds/nonexistent-id/evidence",
                files={"file": ("valid.png", b"bytes", "image/png")},
            )
            assert res_404.status_code == 404
            mock_resume.assert_not_called()

            # 2. 400 Bad Request (disallowed extension)
            res_400 = await client.post(
                f"/refunds/{refund_id}/evidence",
                files={"file": ("document.pdf", b"bytes", "application/pdf")},
            )
            assert res_400.status_code == 400
            mock_resume.assert_not_called()

            # 3. 413 Payload Too Large (> 5MB)
            oversized_bytes = b"x" * (5 * 1024 * 1024 + 1)
            res_413 = await client.post(
                f"/refunds/{refund_id}/evidence",
                files={"file": ("huge.jpg", oversized_bytes, "image/jpeg")},
            )
            assert res_413.status_code == 413
            mock_resume.assert_not_called()


@pytest.mark.asyncio
async def test_evidence_upload_updates_clarification_history_evidence_ids(
    mock_repo: MockRefundRepository,
):
    """AC: When evidence is uploaded, evidence_id is appended to latest ClarificationTurn in clarification_history and returned in GET /refunds/{refund_id}."""
    refund_id = "ref-evidence-turn-test"
    turn = ClarificationTurn(
        cycle=1,
        prompt="Please provide photos of the damaged item",
        response=None,
        timestamp=datetime.now(timezone.utc).isoformat(),
        evidence_ids=[],
    )
    mock_repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1002",
        status="awaiting_clarification",
        clarification_history=[turn],
        clarification_prompt=turn.prompt,
        clarification_count=1,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # POST evidence
        res = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("damage_photo.png", b"fake-png-bytes", "image/png")},
        )
        assert res.status_code == 201
        data = res.json()
        assert len(data["evidence"]) == 1
        ev_id = data["evidence"][0]["evidence_id"]
        assert len(data["clarification_history"]) == 1
        assert data["clarification_history"][0]["cycle"] == 1
        assert data["clarification_history"][0]["prompt"] == "Please provide photos of the damaged item"
        assert ev_id in data["clarification_history"][0]["evidence_ids"]

        # GET /refunds/{refund_id}
        get_res = await client.get(f"/refunds/{refund_id}")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert "clarification_history" in get_data
        assert len(get_data["clarification_history"]) == 1
        assert get_data["clarification_history"][0]["cycle"] == 1
        assert ev_id in get_data["clarification_history"][0]["evidence_ids"]




