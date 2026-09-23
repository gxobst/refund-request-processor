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
from app.schemas.refund import RefundRecord


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


@pytest.fixture
def mock_repo() -> MockRefundRepository:
    repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.clear()


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
                json={"response_text": "The box arrived crushed and item broken."},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == refund_id
    assert data["status"] == "pending"
    assert data["clarification_response"] == "The box arrived crushed and item broken."
    # Verify repository updated
    updated_record = mock_repo.get_refund_request(refund_id)
    assert updated_record is not None
    assert updated_record.status == "pending"
    assert updated_record.clarification_response == "The box arrived crushed and item broken."
    # Verify background task was scheduled
    mock_resume.assert_called_once_with(
        refund_id=refund_id,
        response_text="The box arrived crushed and item broken.",
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
