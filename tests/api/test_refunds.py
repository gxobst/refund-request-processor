"""Unit and API integration tests for FastAPI refund endpoints."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
import pytest


from app.api.refunds import get_repository
from app.main import app
from app.schemas.refund import RefundRecord


class MockRefundRepository:
    """Mock repository for isolated API testing."""

    def __init__(self):
        self.records: dict[str, RefundRecord] = {}

    def create_refund_request(self, order_id: str, customer_request_text: str) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        refund_id = f"ref_mock_{len(self.records) + 1}"
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text,
            status="pending",
            created_at=now_iso,
            updated_at=now_iso,
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
