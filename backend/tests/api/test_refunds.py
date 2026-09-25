"""Unit and API integration tests for FastAPI refund endpoints."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
import pytest


from pathlib import Path
from app.api.refunds import get_repository
from app.main import app
from app.schemas.refund import EvidenceItem, RefundRecord
from app.services.storage import EvidenceStorageService, get_evidence_storage_service


class MockRefundRepository:
    """Mock repository for isolated API testing."""

    def __init__(self):
        self.records: dict[str, RefundRecord] = {}

    def create_refund_request(
        self,
        order_id: str,
        customer_request_text: str,
        evidence: list[EvidenceItem | dict[str, Any]] | None = None,
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        refund_id = f"ref_mock_{len(self.records) + 1}"
        evidence_items: list[EvidenceItem] = []
        if evidence:
            for item in evidence:
                if isinstance(item, EvidenceItem):
                    evidence_items.append(item)
                elif isinstance(item, dict):
                    evidence_items.append(EvidenceItem.model_validate(item))
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text,
            status="pending",
            created_at=now_iso,
            updated_at=now_iso,
            evidence=evidence_items,
        )
        self.records[refund_id] = record
        return record

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        return self.records.get(refund_id)

    def update_decision(
        self,
        refund_id: str,
        decision: str,
        reasoning: str,
        matched_policy_rule: dict[str, Any] | None,
        confidence_score: float,
        status: str,
    ) -> RefundRecord:
        record = self.records[refund_id]
        updated = record.model_copy(
            update={
                "decision": decision,
                "reasoning": reasoning,
                "matched_policy_rule": matched_policy_rule,
                "confidence_score": confidence_score,
                "status": status,
            }
        )
        self.records[refund_id] = updated
        return updated


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


@pytest.fixture(autouse=True)
def mock_workflow_runner(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock_runner = MagicMock()
    monkeypatch.setattr("app.api.refunds.run_refund_workflow", mock_runner)
    return mock_runner


@pytest.mark.asyncio
async def test_submit_refund_request_success(
    mock_repo: MockRefundRepository, mock_workflow_runner: MagicMock
):
    # Arrange
    payload = {
        "order_id": "ORD-1001",
        "customer_request_text": "Item arrived damaged with broken parts.",
    }
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/refunds", json=payload)

    # Assert
    assert response.status_code == 202
    data = response.json()
    assert data["order_id"] == "ORD-1001"
    assert data["status"] == "pending"
    assert data["refund_id"].startswith("ref_mock_")
    assert "created_at" in data

    # Verify record was created in repository
    record = mock_repo.get_refund_request(data["refund_id"])
    assert record is not None
    assert record.order_id == "ORD-1001"
    assert record.evidence == []

    # Verify background workflow execution was scheduled
    mock_workflow_runner.assert_called_once()



@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"order_id": "", "customer_request_text": "Valid text"},
        {"order_id": "   ", "customer_request_text": "Valid text"},
        {"order_id": "ORD-1", "customer_request_text": ""},
        {"order_id": "ORD-1", "customer_request_text": "    \n\t  "},
        {"customer_request_text": "Missing order id"},
        {"order_id": "Missing text"},
        {},
    ],
)
@pytest.mark.asyncio
async def test_submit_refund_request_validation_error(
    invalid_payload: dict, mock_repo: MockRefundRepository
):
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/refunds", json=invalid_payload)

    # Assert
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_refund_request_pending_state(mock_repo: MockRefundRepository):
    # Arrange: seed a pending record
    record = mock_repo.create_refund_request(
        order_id="ORD-2001",
        customer_request_text="Awaiting review.",
    )
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/refunds/{record.refund_id}")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == record.refund_id
    assert data["order_id"] == "ORD-2001"
    assert data["status"] == "pending"
    assert data["decision"] is None


@pytest.mark.asyncio
async def test_get_refund_request_completed_state(mock_repo: MockRefundRepository):
    # Arrange: seed completed record
    record = mock_repo.create_refund_request(
        order_id="ORD-2002",
        customer_request_text="Broken screen.",
    )
    mock_repo.update_decision(
        refund_id=record.refund_id,
        decision="auto_approve",
        reasoning="Within 30-day window and amount under $500.",
        matched_policy_rule={"max_order_amount": 500},
        confidence_score=0.96,
        status="completed",
    )
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/refunds/{record.refund_id}")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == record.refund_id
    assert data["status"] == "completed"
    assert data["decision"] == "auto_approve"
    assert data["reasoning"] == "Within 30-day window and amount under $500."
    assert data["confidence_score"] == 0.96
    assert data["matched_policy_rule"] == {"max_order_amount": 500}


@pytest.mark.asyncio
async def test_get_refund_request_not_found(mock_repo: MockRefundRepository):
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/refunds/nonexistent-id-999")

    # Assert
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_submit_refund_request_multipart_with_image_file(
    mock_repo: MockRefundRepository, mock_workflow_runner: MagicMock
):
    """Test POST /refunds with multipart form data and a valid image file succeeds."""
    # Arrange
    form_data = {
        "order_id": "ORD-1002",
        "customer_request_text": "Item arrived broken with visible cracks.",
    }
    # Minimal valid PNG header + dummy payload
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    files = {"file": ("damage_photo.png", png_bytes, "image/png")}
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/refunds", data=form_data, files=files)

    # Assert
    assert response.status_code == 202
    data = response.json()
    assert data["order_id"] == "ORD-1002"
    assert data["status"] == "pending"
    assert "refund_id" in data

    # Verify repository record
    record = mock_repo.get_refund_request(data["refund_id"])
    assert record is not None
    assert record.order_id == "ORD-1002"
    assert len(record.evidence) == 1
    evidence_item = record.evidence[0]
    assert evidence_item.filename == "damage_photo.png"
    assert evidence_item.content_type == "image/png"
    assert evidence_item.size_bytes == len(png_bytes)
    assert evidence_item.storage_key.startswith("evidence/ORD-1002/")

    # Verify background workflow execution was scheduled with attached evidence
    mock_workflow_runner.assert_called_once()
    runner_kwargs = mock_workflow_runner.call_args[1]
    assert runner_kwargs["refund_id"] == record.refund_id
    assert runner_kwargs["order_id"] == "ORD-1002"
    assert runner_kwargs["evidence"] == record.evidence


@pytest.mark.parametrize(
    "missing_field_data",
    [
        {"customer_request_text": "Missing order id entirely"},
        {"order_id": "", "customer_request_text": "Empty order id"},
        {"order_id": "   ", "customer_request_text": "Whitespace order id"},
        {"order_id": "ORD-1003"},
        {"order_id": "ORD-1003", "customer_request_text": ""},
        {"order_id": "ORD-1003", "customer_request_text": "   \n\t "},
    ],
)
@pytest.mark.asyncio
async def test_submit_refund_request_multipart_missing_required_fields(
    missing_field_data: dict, mock_repo: MockRefundRepository
):
    """Test POST /refunds with missing order_id or customer_request_text in multipart form returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/refunds", data=missing_field_data)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "disallowed_filename, dis_content_type",
    [
        ("damage_video.mp4", "video/mp4"),
        ("clip.mov", "video/quicktime"),
        ("report.pdf", "application/pdf"),
        ("evidence.txt", "text/plain"),
    ],
)
@pytest.mark.asyncio
async def test_submit_refund_request_disallowed_file_extension(
    disallowed_filename: str, dis_content_type: str, mock_repo: MockRefundRepository
):
    """Test POST /refunds with disallowed file extension returns HTTP 400 Bad Request."""
    form_data = {
        "order_id": "ORD-1005",
        "customer_request_text": "Damaged goods.",
    }
    files = {"file": (disallowed_filename, b"fake_binary_payload", dis_content_type)}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/refunds", data=form_data, files=files)

    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "disallowed file extension" in detail


@pytest.mark.asyncio
async def test_submit_refund_request_file_exceeds_size_limit(mock_repo: MockRefundRepository):
    """Test POST /refunds with an image file exceeding 5MB returns HTTP 413 Payload Too Large."""
    form_data = {
        "order_id": "ORD-1006",
        "customer_request_text": "Large file upload attempt.",
    }
    oversized_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * (5 * 1024 * 1024 + 100)
    files = {"file": ("giant_photo.jpg", oversized_bytes, "image/jpeg")}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/refunds", data=form_data, files=files)

    assert response.status_code == 413
    detail = response.json()["detail"].lower()
    assert "exceeds maximum allowed limit" in detail


@pytest.mark.asyncio
async def test_submit_refund_request_openapi_schema():
    """Test GET /openapi.json documents both application/json and multipart/form-data for POST /refunds."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    post_refunds = schema["paths"]["/refunds"]["post"]
    content = post_refunds["requestBody"]["content"]

    # Verify both content types are documented
    assert "application/json" in content
    assert "multipart/form-data" in content

    # Verify JSON schema properties
    json_props = content["application/json"]["schema"]["properties"]
    assert "order_id" in json_props
    assert "customer_request_text" in json_props

    # Verify multipart schema properties including binary file
    form_schema = content["multipart/form-data"]["schema"]
    form_props = form_schema["properties"]
    assert "order_id" in form_props
    assert "customer_request_text" in form_props
    assert "file" in form_props
    assert form_props["file"]["type"] == "string"
    assert form_props["file"]["format"] == "binary"
    # Verify file is optional (not in required fields)
    assert "file" not in form_schema.get("required", [])

