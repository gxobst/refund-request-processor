"""API integration tests for multipart evidence upload endpoint (POST /refunds/{refund_id}/evidence)."""

from datetime import datetime, timezone
from typing import Any
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.db.repository import RefundNotFoundError
from app.main import app
from app.schemas.refund import EvidenceItem, RefundRecord


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
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text,
            status=status,
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
        updated = record.model_copy(
            update={
                "evidence": evidence_list,
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

        # Second upload: unboxing video
        res2 = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("unboxing.mp4", b"video-mp4-bytes", "video/mp4")},
        )
        assert res2.status_code == 201
        assert len(res2.json()["evidence"]) == 2

    stored = mock_repo.get_refund_request(refund_id)
    assert stored is not None
    assert len(stored.evidence) == 2
    assert stored.evidence[0].filename == "item_photo.png"
    assert stored.evidence[1].filename == "unboxing.mp4"


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
    """Test POST /refunds/{refund_id}/evidence returns 413 when image exceeds 10MB limit."""
    refund_id = "ref-oversized-image"
    mock_repo.seed_record(refund_id=refund_id)
    transport = ASGITransport(app=app)

    oversized_bytes = b"x" * (10 * 1024 * 1024 + 1)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("huge_photo.jpg", oversized_bytes, "image/jpeg")},
        )

    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_evidence_video_size_exceeded_413(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/evidence returns 413 when video exceeds 50MB limit."""
    refund_id = "ref-oversized-video"
    mock_repo.seed_record(refund_id=refund_id)
    transport = ASGITransport(app=app)

    oversized_bytes = b"v" * (50 * 1024 * 1024 + 1)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("huge_video.mp4", oversized_bytes, "video/mp4")},
        )

    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["detail"].lower()


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

