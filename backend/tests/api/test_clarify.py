"""Unit and API integration tests for customer clarification response endpoint and workflow resumption."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
import pytest

from app.api.refunds import get_repository
from app.db.repository import RefundNotFoundError
from app.graph.runner import resume_refund_workflow, run_refund_workflow
from app.main import app
from app.schemas.classifier import ClassificationOutput
from app.schemas.refund import EvidenceItem, RefundRecord


class MockRefundRepository:
    """Mock repository for clarification response testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str = "ORD-1001",
        status: str = "awaiting_clarification",
        customer_request_text: str = "Need refund for order",
        clarification_prompt: str | None = "Please provide details",
        clarification_response: str | None = None,
        clarification_count: int = 1,
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text,
            status=status,
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
        updated = record.model_copy(
            update={
                "clarification_response": clarification_response,
                "status": "pending",
                "updated_at": now_iso,
            }
        )
        self.records[refund_id] = updated
        return updated

    def update_decision(
        self,
        refund_id: str,
        decision: str,
        reasoning: str,
        matched_policy_rule: dict[str, Any] | None,
        confidence_score: float,
        status: str,
    ) -> RefundRecord:
        record = self.records.get(refund_id)
        if record is None:
            raise RefundNotFoundError(f"Refund request '{refund_id}' not found.")
        now_iso = datetime.now(timezone.utc).isoformat()
        updated = record.model_copy(
            update={
                "decision": decision,
                "reasoning": reasoning,
                "matched_policy_rule": matched_policy_rule,
                "confidence_score": confidence_score,
                "status": status,
                "updated_at": now_iso,
            }
        )
        self.records[refund_id] = updated
        return updated

    def add_evidence(
        self, refund_id: str, evidence_item: Any
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
async def test_clarify_success_200(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify successfully submits response and sets status to pending."""
    refund_id = "ref-clarify-1"
    mock_repo.seed_record(
        refund_id=refund_id,
        status="awaiting_clarification",
        customer_request_text="Damaged item, not sure how",
    )
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/refunds/{refund_id}/clarify",
                json={"response_text": "Item was damaged"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == refund_id
    assert data["status"] == "pending"
    assert data["clarification_response"] == "Item was damaged"
    # Verify repository updated
    updated_record = mock_repo.get_refund_request(refund_id)
    assert updated_record is not None
    assert updated_record.status == "pending"
    assert updated_record.clarification_response == "Item was damaged"
    # Verify background task was scheduled
    mock_resume.assert_called_once_with(
        refund_id=refund_id,
        response_text="Item was damaged",
        repository=mock_repo,
    )


@pytest.mark.asyncio
async def test_clarify_not_found_404(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify returns 404 for unknown refund_id."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/nonexistent-id/clarify",
            json={"response_text": "Some response."},
        )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_status", ["pending", "completed", "escalated"])
async def test_clarify_invalid_status_400(
    mock_repo: MockRefundRepository, invalid_status: str
):
    """Test POST /refunds/{refund_id}/clarify returns 400 when record status is not awaiting_clarification."""
    refund_id = f"ref-invalid-{invalid_status}"
    mock_repo.seed_record(refund_id=refund_id, status=invalid_status)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": "Valid clarification response text."},
        )

    assert response.status_code == 400
    assert "not awaiting clarification" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("blank_text", ["", "   ", "   \n\t  "])
async def test_clarify_blank_text_422(
    mock_repo: MockRefundRepository, blank_text: str
):
    """Test POST /refunds/{refund_id}/clarify returns 422 when response_text is blank or whitespace."""
    refund_id = "ref-blank-clarify"
    mock_repo.seed_record(refund_id=refund_id, status="awaiting_clarification")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": blank_text},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_clarify_missing_body_422(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify returns 422 when response_text is omitted."""
    refund_id = "ref-missing-body"
    mock_repo.seed_record(refund_id=refund_id, status="awaiting_clarification")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_resume_refund_workflow_with_checkpointer(monkeypatch: pytest.MonkeyPatch):
    """Test resume_refund_workflow loads checkpoint state, updates customer text, and resumes to completion."""
    checkpointer = MemorySaver()
    thread_id = "thread_resume_test_1"
    refund_id = "ref_resume_test_1"

    # Step 1: Initial run with low confidence to pause at awaiting_clarification
    low_conf = ClassificationOutput(
        category="damaged",
        confidence_score=0.45,
        reasoning="Vague description of damage.",
    )
    mock_llm_low = MagicMock()
    mock_llm_low.with_structured_output.return_value = RunnableLambda(lambda _: low_conf)
    monkeypatch.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm_low)

    initial_state = await run_refund_workflow(
        refund_id=refund_id,
        order_id="ORD-1001",
        customer_request_text="Need refund, something broken.",
        thread_id=thread_id,
        checkpointer=checkpointer,
    )
    assert initial_state["status"] == "awaiting_clarification"
    assert initial_state["clarification_count"] == 1

    # Step 2: Resume with high confidence classification on the clarified text
    high_conf = ClassificationOutput(
        category="damaged",
        confidence_score=0.95,
        reasoning="Customer provided clear evidence of damage occurred in transit.",
    )
    mock_llm_high = MagicMock()
    mock_llm_high.with_structured_output.return_value = RunnableLambda(lambda _: high_conf)
    monkeypatch.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm_high)

    resumed_state = await resume_refund_workflow(
        refund_id=refund_id,
        response_text="The armrest was completely sheared off in shipping.",
        thread_id=thread_id,
        checkpointer=checkpointer,
    )

    assert resumed_state["status"] == "completed"
    assert resumed_state["decision"] == "auto_approve"
    assert "Need refund, something broken.\n[Clarification]: The armrest was completely sheared off in shipping." in resumed_state["customer_request_text"]
    assert resumed_state["clarification_response"] == "The armrest was completely sheared off in shipping."
    assert resumed_state["needs_clarification"] is False


@pytest.mark.asyncio
async def test_resume_refund_workflow_fallback_to_repository(monkeypatch: pytest.MonkeyPatch):
    """Test resume_refund_workflow recovers state from repository when checkpointer has no state."""
    checkpointer = MemorySaver()  # Empty checkpointer with no existing state
    repo = MockRefundRepository()
    refund_id = "ref_fallback_test_1"
    repo.seed_record(
        refund_id=refund_id,
        order_id="ORD-1001",
        status="pending",
        customer_request_text="Initial ambiguous text",
        clarification_count=1,
    )

    high_conf = ClassificationOutput(
        category="damaged",
        confidence_score=0.92,
        reasoning="Clear explanation of damaged item.",
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda _: high_conf)
    monkeypatch.setattr("app.agents.classifier.get_bedrock_llm", lambda: mock_llm)

    resumed_state = await resume_refund_workflow(
        refund_id=refund_id,
        response_text="Customer clarification response details.",
        thread_id="nonexistent_thread",
        checkpointer=checkpointer,
        repository=repo,
    )

    assert resumed_state["status"] == "completed"
    assert resumed_state["decision"] == "auto_approve"
    assert "Initial ambiguous text\n[Clarification]: Customer clarification response details." in resumed_state["customer_request_text"]
    assert resumed_state["clarification_response"] == "Customer clarification response details."
    # Verify repository was updated with the final decision
    updated_rec = repo.get_refund_request(refund_id)
    assert updated_rec is not None
    assert updated_rec.status == "completed"
    assert updated_rec.decision == "auto_approve"


@pytest.mark.asyncio
async def test_clarify_multipart_form_without_file(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify accepts multipart form without attached file."""
    refund_id = "ref-clarify-multipart-1"
    mock_repo.seed_record(refund_id=refund_id, status="awaiting_clarification")
    transport = ASGITransport(app=app)

    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/refunds/{refund_id}/clarify",
                data={"response_text": "Clarification provided via form."},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == refund_id
    assert data["status"] == "pending"
    assert data["clarification_response"] == "Clarification provided via form."
    assert data["evidence"] == []


@pytest.mark.asyncio
async def test_clarify_multipart_form_with_evidence_file(mock_repo: MockRefundRepository, tmp_path):
    """Test POST /refunds/{refund_id}/clarify accepts multipart form with attached evidence file."""
    refund_id = "ref-clarify-multipart-2"
    mock_repo.seed_record(refund_id=refund_id, order_id="ORD-1002", status="awaiting_clarification")
    transport = ASGITransport(app=app)

    file_bytes = b"fake-jpeg-photo-damage-proof"
    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/refunds/{refund_id}/clarify",
                data={"response_text": "Attached photo of crushed box and broken screen."},
                files={"file": ("box_damage.jpg", file_bytes, "image/jpeg")},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert len(data["evidence"]) == 1
    evidence = data["evidence"][0]
    assert evidence["filename"] == "box_damage.jpg"
    assert evidence["content_type"] == "image/jpeg"
    assert evidence["size_bytes"] == len(file_bytes)
    assert evidence["storage_key"].startswith("evidence/ORD-1002/")


@pytest.mark.asyncio
async def test_clarify_multipart_form_blank_response_text_422(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify returns 422 when response_text is blank in form data."""
    refund_id = "ref-clarify-multipart-blank"
    mock_repo.seed_record(refund_id=refund_id, status="awaiting_clarification")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/clarify",
            data={"response_text": "   "},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_clarify_multipart_form_disallowed_extension_400(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify returns 400 when attached file has disallowed extension."""
    refund_id = "ref-clarify-disallowed-ext"
    mock_repo.seed_record(refund_id=refund_id, status="awaiting_clarification")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/clarify",
            data={"response_text": "Exploit script attached."},
            files={"file": ("malware.exe", b"MZ...", "image/jpeg")},
        )
    assert response.status_code == 400
    assert "disallowed file extension" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_clarify_multipart_form_disallowed_mime_400(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify returns 400 when attached file has disallowed MIME type."""
    refund_id = "ref-clarify-disallowed-mime"
    mock_repo.seed_record(refund_id=refund_id, status="awaiting_clarification")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/clarify",
            data={"response_text": "PDF invoice attached."},
            files={"file": ("invoice.jpg", b"%PDF-1.4", "application/pdf")},
        )
    assert response.status_code == 400
    assert "unsupported content type" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_clarify_multipart_form_oversized_file_413(mock_repo: MockRefundRepository):
    """Test POST /refunds/{refund_id}/clarify returns 413 when attached file exceeds size limits."""
    refund_id = "ref-clarify-oversized"
    mock_repo.seed_record(refund_id=refund_id, status="awaiting_clarification")
    transport = ASGITransport(app=app)

    oversized_data = b"0" * (10 * 1024 * 1024 + 1)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/clarify",
            data={"response_text": "Oversized photo."},
            files={"file": ("huge.jpg", oversized_data, "image/jpeg")},
        )
    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_clarify_openapi_schema():
    """Unit test: GET /openapi.json defines both application/json and multipart/form-data content types with binary format for evidence_file."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    endpoint = spec["paths"]["/refunds/{refund_id}/clarify"]["post"]
    assert "requestBody" in endpoint
    request_body = endpoint["requestBody"]
    assert request_body.get("required") is True
    content = request_body["content"]

    # Verify application/json content type
    assert "application/json" in content
    json_schema = content["application/json"]["schema"]
    assert json_schema["type"] == "object"
    assert "response_text" in json_schema["properties"]
    assert json_schema["properties"]["response_text"]["type"] == "string"
    assert "response_text" in json_schema["required"]

    # Verify multipart/form-data content type
    assert "multipart/form-data" in content
    form_schema = content["multipart/form-data"]["schema"]
    assert form_schema["type"] == "object"
    assert "response_text" in form_schema["properties"]
    assert form_schema["properties"]["response_text"]["type"] == "string"
    assert "response_text" in form_schema["required"]
    assert "evidence_file" in form_schema["properties"]
    assert form_schema["properties"]["evidence_file"]["type"] == "string"
    assert form_schema["properties"]["evidence_file"]["format"] == "binary"


@pytest.mark.asyncio
async def test_clarify_multipart_form_with_evidence_file_parameter(
    mock_repo: MockRefundRepository, tmp_path: Path
):
    """Integration test: submitting a multipart form body with response_text and evidence_file succeeds with HTTP 200 and attaches evidence."""
    refund_id = "ref-clarify-multipart-evidence-param"
    mock_repo.seed_record(refund_id=refund_id, order_id="ORD-1003", status="awaiting_clarification")
    transport = ASGITransport(app=app)

    file_bytes = b"fake-jpeg-photo-damage-evidence-param"
    with patch("app.api.refunds.resume_refund_workflow", new_callable=AsyncMock) as mock_resume:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/refunds/{refund_id}/clarify",
                data={"response_text": "Item was damaged and here is the evidence file."},
                files={"evidence_file": ("damaged_item.jpg", file_bytes, "image/jpeg")},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["clarification_response"] == "Item was damaged and here is the evidence file."
    assert len(data["evidence"]) == 1
    evidence = data["evidence"][0]
    assert evidence["filename"] == "damaged_item.jpg"
    assert evidence["content_type"] == "image/jpeg"
    assert evidence["size_bytes"] == len(file_bytes)
    assert evidence["storage_key"].startswith("evidence/ORD-1003/")
    mock_resume.assert_called_once_with(
        refund_id=refund_id,
        response_text="Item was damaged and here is the evidence file.",
        repository=mock_repo,
    )

