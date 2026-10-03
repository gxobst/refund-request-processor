"""Unit and API integration tests for refund queue listing and manual override endpoints."""

from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.db.repository import RefundNotFoundError
from app.main import app
from app.schemas.refund import RefundRecord


class MockRefundRepository:
    """Mock repository for queue listing and override testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str,
        status: str,
        created_at: str | None = None,
        decision: str | None = None,
        reasoning: str | None = None,
    ) -> RefundRecord:
        now_iso = created_at or datetime.now(timezone.utc).isoformat()
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=f"Request for {order_id}",
            status=status,
            decision=decision,
            reasoning=reasoning,
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.records[refund_id] = record
        return record

    def list_refund_requests(
        self, status: str | None = None, limit: int = 50
    ) -> list[RefundRecord]:
        records = list(self.records.values())
        if status is not None:
            records = [r for r in records if r.status.lower() == status.strip().lower()]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        return self.records.get(refund_id)

    def apply_override(
        self,
        refund_id: str,
        override_decision: str,
        override_reason: str,
        approval_email_text: str | None = None,
        denial_email_text: str | None = None,
        overridden_by: str | None = "supervisor",
        escalation_tier: str | None = None,
    ) -> RefundRecord:
        record = self.records.get(refund_id)
        if record is None:
            raise RefundNotFoundError(f"Refund request '{refund_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        if override_decision in ("approve", "auto_approve"):
            if approval_email_text is None:
                from app.agents.approval_notifier import generate_approval_email
                approval_email_text = generate_approval_email(order_id=record.order_id, refund_id=refund_id)
            denial_email_text = None
        elif override_decision == "deny":
            if denial_email_text is None:
                from app.agents.denial_notifier import generate_denial_email
                denial_email_text = generate_denial_email(
                    order_id=record.order_id,
                    refund_id=refund_id,
                    policy_reasoning=override_reason,
                )
            approval_email_text = None
        else:
            approval_email_text = None
            denial_email_text = None

        updated = record.model_copy(
            update={
                "override_decision": override_decision,
                "override_reason": override_reason,
                "overridden_at": now_iso,
                "overridden_by": overridden_by,
                "updated_at": now_iso,
                "decision": override_decision,
                "status": "completed",
                "approval_email_text": approval_email_text,
                "denial_email_text": denial_email_text,
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
async def test_list_refunds_all(mock_repo: MockRefundRepository):
    # Arrange: seed multiple records
    mock_repo.seed_record("ref-1", "ORD-001", "pending", "2026-09-01T10:00:00Z")
    mock_repo.seed_record("ref-2", "ORD-002", "escalated", "2026-09-02T10:00:00Z")
    mock_repo.seed_record("ref-3", "ORD-003", "completed", "2026-09-03T10:00:00Z")

    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/refunds")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # Verify sorting by created_at descending
    assert [item["refund_id"] for item in data] == ["ref-3", "ref-2", "ref-1"]


@pytest.mark.asyncio
async def test_list_refunds_filter_escalated(mock_repo: MockRefundRepository):
    # Arrange: seed records across different statuses
    mock_repo.seed_record("ref-1", "ORD-001", "pending")
    mock_repo.seed_record("ref-2", "ORD-002", "escalated")
    mock_repo.seed_record("ref-3", "ORD-003", "escalated")
    mock_repo.seed_record("ref-4", "ORD-004", "completed")

    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/refunds?status=escalated")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(item["status"] == "escalated" for item in data)
    assert {item["refund_id"] for item in data} == {"ref-2", "ref-3"}


@pytest.mark.asyncio
async def test_list_refunds_filter_pending_and_completed(mock_repo: MockRefundRepository):
    mock_repo.seed_record("ref-1", "ORD-001", "pending")
    mock_repo.seed_record("ref-2", "ORD-002", "completed")

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_pending = await client.get("/refunds?status=pending")
        res_completed = await client.get("/refunds?status=completed")

    assert res_pending.status_code == 200
    pending_data = res_pending.json()
    assert len(pending_data) == 1
    assert pending_data[0]["refund_id"] == "ref-1"

    assert res_completed.status_code == 200
    completed_data = res_completed.json()
    assert len(completed_data) == 1
    assert completed_data[0]["refund_id"] == "ref-2"


@pytest.mark.asyncio
async def test_list_refunds_invalid_status_returns_422(mock_repo: MockRefundRepository):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/refunds?status=invalid_status")

    assert response.status_code == 422


@pytest.mark.parametrize("route_prefix", ["/refunds", "/v1/refunds"])
@pytest.mark.asyncio
async def test_list_refunds_filter_awaiting_clarification(
    route_prefix: str, mock_repo: MockRefundRepository
):
    # Arrange: seed records across all four valid statuses
    mock_repo.seed_record("ref-p1", "ORD-1001", "pending")
    mock_repo.seed_record("ref-c1", "ORD-1002", "completed")
    mock_repo.seed_record("ref-e1", "ORD-1003", "escalated")
    mock_repo.seed_record("ref-ac1", "ORD-1004", "awaiting_clarification")
    mock_repo.seed_record("ref-ac2", "ORD-1005", "awaiting_clarification")

    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"{route_prefix}?status=awaiting_clarification")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(item["status"] == "awaiting_clarification" for item in data)
    assert {item["refund_id"] for item in data} == {"ref-ac1", "ref-ac2"}
    assert not any(item["status"] in ("pending", "completed", "escalated") for item in data)


@pytest.mark.parametrize("route_prefix", ["/refunds", "/v1/refunds"])
@pytest.mark.parametrize(
    "status_filter", ["pending", "completed", "escalated", "awaiting_clarification"]
)
@pytest.mark.asyncio
async def test_list_refunds_filter_each_valid_status(
    route_prefix: str, status_filter: str, mock_repo: MockRefundRepository
):
    # Arrange: seed records across all four valid statuses
    mock_repo.seed_record("ref-pen", "ORD-0001", "pending")
    mock_repo.seed_record("ref-com", "ORD-0002", "completed")
    mock_repo.seed_record("ref-esc", "ORD-0003", "escalated")
    mock_repo.seed_record("ref-cla", "ORD-0004", "awaiting_clarification")

    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"{route_prefix}?status={status_filter}")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == status_filter
    other_statuses = {"pending", "completed", "escalated", "awaiting_clarification"} - {status_filter}
    assert all(item["status"] not in other_statuses for item in data)


@pytest.mark.parametrize("route_prefix", ["/refunds", "/v1/refunds"])
@pytest.mark.asyncio
async def test_list_refunds_filter_zero_matching_records_returns_empty_list(
    route_prefix: str, mock_repo: MockRefundRepository
):
    # Arrange: seed records only for pending and completed
    mock_repo.seed_record("ref-1", "ORD-0001", "pending")
    mock_repo.seed_record("ref-2", "ORD-0002", "completed")

    transport = ASGITransport(app=app)

    # Act & Assert for statuses with 0 matching records
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_clarification = await client.get(f"{route_prefix}?status=awaiting_clarification")
        res_escalated = await client.get(f"{route_prefix}?status=escalated")

    assert res_clarification.status_code == 200
    assert res_clarification.json() == []

    assert res_escalated.status_code == 200
    assert res_escalated.json() == []


@pytest.mark.parametrize("route_prefix", ["/refunds", "/v1/refunds"])
@pytest.mark.asyncio
async def test_list_refunds_unparameterized_returns_all_records(
    route_prefix: str, mock_repo: MockRefundRepository
):
    # Arrange: seed records across all four statuses
    mock_repo.seed_record("ref-1", "ORD-0001", "pending")
    mock_repo.seed_record("ref-2", "ORD-0002", "completed")
    mock_repo.seed_record("ref-3", "ORD-0003", "escalated")
    mock_repo.seed_record("ref-4", "ORD-0004", "awaiting_clarification")

    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(route_prefix)

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4
    returned_statuses = {item["status"] for item in data}
    assert returned_statuses == {"pending", "completed", "escalated", "awaiting_clarification"}


@pytest.mark.parametrize("route_prefix", ["/refunds", "/v1/refunds"])
@pytest.mark.parametrize(
    "invalid_status",
    [
        "invalid_status",
        "unknown",
        "cancelled",
        "approved",
        "rejected",
        "AWAITING_CLARIFICATION_INVALID",
    ],
)
@pytest.mark.asyncio
async def test_list_refunds_invalid_status_returns_422_on_all_routes(
    route_prefix: str, invalid_status: str, mock_repo: MockRefundRepository
):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"{route_prefix}?status={invalid_status}")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_refunds_with_limit(mock_repo: MockRefundRepository):
    for i in range(5):
        mock_repo.seed_record(f"ref-{i}", f"ORD-{i}", "pending", f"2026-09-0{i+1}T10:00:00Z")

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/refunds?limit=2")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_override_refund_decision_approve(mock_repo: MockRefundRepository):
    # Arrange: seed an escalated record
    mock_repo.seed_record(
        refund_id="ref-esc-1",
        order_id="ORD-3001",
        status="escalated",
        decision="escalate",
        reasoning="Policy ambiguous, requires supervisor review.",
    )
    transport = ASGITransport(app=app)
    override_payload = {
        "override_decision": "approve",
        "reason": "Customer is a high-value VIP account. Exception granted.",
    }

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/ref-esc-1/override",
            json=override_payload,
            headers={"X-User-Role": "supervisor"},
        )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == "ref-esc-1"
    assert data["decision"] == "approve"
    assert data["status"] == "completed"
    assert data["override_decision"] == "approve"
    assert data["override_reason"] == "Customer is a high-value VIP account. Exception granted."
    assert data["overridden_at"] is not None
    assert data["approval_email_text"] is not None
    assert "Dear Customer," in data["approval_email_text"]
    assert "ORD-3001" in data["approval_email_text"]
    assert "RMA" in data["approval_email_text"]
    assert data["denial_email_text"] is None

    # Verify repository state
    stored = mock_repo.get_refund_request("ref-esc-1")
    assert stored is not None
    assert stored.decision == "approve"
    assert stored.status == "completed"
    assert stored.override_decision == "approve"
    assert stored.override_reason == "Customer is a high-value VIP account. Exception granted."
    assert stored.approval_email_text is not None
    assert stored.denial_email_text is None


@pytest.mark.asyncio
async def test_override_refund_decision_deny(mock_repo: MockRefundRepository):
    # Arrange: seed an escalated record
    mock_repo.seed_record(
        refund_id="ref-esc-2",
        order_id="ORD-3002",
        status="escalated",
        decision="escalate",
        reasoning="Low classification confidence.",
    )
    transport = ASGITransport(app=app)
    override_payload = {
        "override_decision": "deny",
        "reason": "Item was inspected and shows clear signs of customer damage.",
    }

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/ref-esc-2/override",
            json=override_payload,
            headers={"X-User-Role": "supervisor"},
        )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == "ref-esc-2"
    assert data["decision"] == "deny"
    assert data["status"] == "completed"
    assert data["override_decision"] == "deny"
    assert data["override_reason"] == "Item was inspected and shows clear signs of customer damage."
    assert data["overridden_at"] is not None
    assert data["approval_email_text"] is None
    assert data["denial_email_text"] is not None
    assert "Dear Customer," in data["denial_email_text"]
    assert "ORD-3002" in data["denial_email_text"]
    assert "RMA" not in data["denial_email_text"]

    # Verify repository state
    stored = mock_repo.get_refund_request("ref-esc-2")
    assert stored is not None
    assert stored.decision == "deny"
    assert stored.status == "completed"
    assert stored.approval_email_text is None
    assert stored.denial_email_text is not None


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"override_decision": "maybe", "reason": "Not sure"},
        {"override_decision": "auto_approve", "reason": "Trying to use agent decision"},
        {"override_decision": "unsupported", "reason": "Unsupported decision"},
        {"override_decision": "approve", "reason": ""},
        {"override_decision": "approve", "reason": "    \n\t  "},
        {"override_decision": "approve"},
        {"reason": "Missing decision entirely"},
        {},
    ],
)
@pytest.mark.asyncio
async def test_override_refund_decision_validation_errors(
    invalid_payload: dict, mock_repo: MockRefundRepository
):
    mock_repo.seed_record("ref-esc-3", "ORD-3003", "escalated")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/ref-esc-3/override",
            json=invalid_payload,
            headers={"X-User-Role": "supervisor"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_override_refund_nonexistent_id_returns_404(mock_repo: MockRefundRepository):
    transport = ASGITransport(app=app)
    override_payload = {
        "override_decision": "approve",
        "reason": "Valid reason for nonexistent record.",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/nonexistent-ref-id/override",
            json=override_payload,
            headers={"X-User-Role": "supervisor"},
        )

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()
