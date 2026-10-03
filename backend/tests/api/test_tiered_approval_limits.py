"""Unit and integration tests for role-based tiered refund approval limits and multi-tier escalation."""

from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.auth.jwt import create_jwt_token
from app.auth.rbac import DEFAULT_ROLE, get_approval_limit_for_role
from app.core.config import get_settings
from app.db.repository import RefundNotFoundError
from app.main import app
from app.policy.schema import DEFAULT_ROLE_APPROVAL_LIMITS, RoleApprovalLimits
from app.schemas.refund import RefundRecord


class MockTieredRefundRepository:
    """In-memory mock repository for tiered approval limits testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str = "ORD-1001",
        status: str = "escalated",
        decision: str | None = "escalate",
        reasoning: str | None = "Tiered approval required",
        refund_amount: float | None = None,
        order_amount: float | None = None,
        escalation_tier: str | None = None,
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=f"Request for {order_id}",
            status=status,
            decision=decision,
            reasoning=reasoning,
            refund_amount=refund_amount,
            order_amount=order_amount,
            escalation_tier=escalation_tier,
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.records[refund_id] = record
        return record

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
        dec_lower = override_decision.strip().lower()
        if dec_lower in ("escalate", "escalated"):
            status_val = "escalated"
            decision_val = "escalate"
            tier_val = escalation_tier or "senior_manager"
        elif dec_lower in ("approve", "auto_approve"):
            status_val = "completed"
            decision_val = "approve"
            tier_val = escalation_tier
        elif dec_lower in ("deny", "denied"):
            status_val = "completed"
            decision_val = "deny"
            tier_val = escalation_tier
        else:
            status_val = "completed"
            decision_val = override_decision
            tier_val = escalation_tier

        updated = record.model_copy(
            update={
                "override_decision": override_decision,
                "override_reason": override_reason,
                "overridden_at": now_iso,
                "overridden_by": overridden_by,
                "updated_at": now_iso,
                "decision": decision_val,
                "status": status_val,
                "escalation_tier": tier_val,
            }
        )
        self.records[refund_id] = updated
        return updated


@pytest.fixture
def mock_repo() -> MockTieredRefundRepository:
    repo = MockTieredRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_repository, None)


# --- Unit Tests for Role Approval Limits Configuration and RBAC Helpers ---


def test_role_approval_limits_constants():
    """Verify default approval limits and Pydantic model defaults."""
    assert DEFAULT_ROLE == "agent"
    assert DEFAULT_ROLE_APPROVAL_LIMITS["agent"] == 100.0
    assert DEFAULT_ROLE_APPROVAL_LIMITS["supervisor"] == 500.0
    assert DEFAULT_ROLE_APPROVAL_LIMITS["senior_manager"] == 2500.0

    model = RoleApprovalLimits()
    assert model.agent == 100.0
    assert model.supervisor == 500.0
    assert model.senior_manager == 2500.0


def test_get_approval_limit_for_role():
    """Verify get_approval_limit_for_role returns expected tiered financial limits."""
    assert get_approval_limit_for_role("agent") == 100.0
    assert get_approval_limit_for_role("AGENT") == 100.0
    assert get_approval_limit_for_role("supervisor") == 500.0
    assert get_approval_limit_for_role("Supervisor") == 500.0
    assert get_approval_limit_for_role("senior_manager") == 2500.0
    assert get_approval_limit_for_role("SENIOR_MANAGER") == 2500.0

    # Unrecognized / empty roles default to agent limit (100.0)
    assert get_approval_limit_for_role("guest") == 100.0
    assert get_approval_limit_for_role("") == 100.0
    assert get_approval_limit_for_role(None) == 100.0


# --- API Integration Tests for Role-Based Tiered Override Limits ---


@pytest.mark.asyncio
async def test_agent_approves_within_limit_succeeds(mock_repo: MockTieredRefundRepository):
    """Agent approving $80 refund succeeds with HTTP 200 OK."""
    mock_repo.seed_record("ref-tier-1", refund_amount=80.0)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Authorized agent adjustment."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-tier-1/override",
            json=payload,
            headers={"X-User-Role": "agent", "X-User-Id": "agent-007"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == "ref-tier-1"
    assert data["decision"] == "approve"
    assert data["status"] == "completed"
    assert data["overridden_by"] == "agent-007"


@pytest.mark.asyncio
async def test_agent_approves_exceeding_limit_returns_403(mock_repo: MockTieredRefundRepository):
    """Agent attempting to approve $150 refund returns HTTP 403 Forbidden with RFC 9457 ProblemDetails."""
    mock_repo.seed_record("ref-tier-2", refund_amount=150.0)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Agent approving over limit."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-tier-2/override",
            json=payload,
            headers={"X-User-Role": "agent"},
        )

    assert response.status_code == 403
    problem = response.json().get("detail", response.json())
    assert problem["type"] == "urn:problem:forbidden"
    assert problem["title"] == "Forbidden"
    assert problem["status"] == 403
    assert "Refund amount $150.00 exceeds your agent approval limit of $100.00" in problem["detail"]
    assert "Escalation to senior approval required." in problem["detail"]


@pytest.mark.asyncio
async def test_supervisor_approves_within_limit_succeeds(mock_repo: MockTieredRefundRepository):
    """Supervisor approving $400 refund succeeds with HTTP 200 OK."""
    mock_repo.seed_record("ref-tier-3", refund_amount=400.0)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Supervisor customer loyalty approval."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-tier-3/override",
            json=payload,
            headers={"X-User-Role": "supervisor"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approve"
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_supervisor_approves_exceeding_limit_returns_403(mock_repo: MockTieredRefundRepository):
    """Supervisor attempting to approve $1,200 refund returns HTTP 403 Forbidden ProblemDetails."""
    mock_repo.seed_record("ref-tier-4", refund_amount=1200.0)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "High-value supervisor exception."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-tier-4/override",
            json=payload,
            headers={"X-User-Role": "supervisor"},
        )

    assert response.status_code == 403
    problem = response.json().get("detail", response.json())
    assert problem["type"] == "urn:problem:forbidden"
    assert problem["title"] == "Forbidden"
    assert problem["status"] == 403
    assert "Refund amount $1200.00 exceeds your supervisor approval limit of $500.00" in problem["detail"]


@pytest.mark.asyncio
async def test_senior_manager_approves_within_limit_succeeds(mock_repo: MockTieredRefundRepository):
    """Senior Manager approving $2,000 refund succeeds with HTTP 200 OK."""
    mock_repo.seed_record("ref-tier-5", refund_amount=2000.0)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Senior management authorization."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-tier-5/override",
            json=payload,
            headers={"X-User-Role": "senior_manager"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approve"
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_senior_manager_approves_exceeding_limit_returns_403(mock_repo: MockTieredRefundRepository):
    """Senior Manager attempting to approve $3,000 refund returns HTTP 403 Forbidden ProblemDetails."""
    mock_repo.seed_record("ref-tier-6", refund_amount=3000.0)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Executive over limit."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-tier-6/override",
            json=payload,
            headers={"X-User-Role": "senior_manager"},
        )

    assert response.status_code == 403
    problem = response.json().get("detail", response.json())
    assert problem["type"] == "urn:problem:forbidden"
    assert problem["title"] == "Forbidden"
    assert problem["status"] == 403
    assert "Refund amount $3000.00 exceeds your senior_manager approval limit of $2500.00" in problem["detail"]


@pytest.mark.parametrize(
    ("role", "boundary_amount"),
    [
        ("agent", 100.0),
        ("supervisor", 500.0),
        ("senior_manager", 2500.0),
    ],
)
@pytest.mark.asyncio
async def test_exact_boundary_limits_succeed(
    mock_repo: MockTieredRefundRepository, role: str, boundary_amount: float
):
    """Exact approval boundaries (Agent $100, Supervisor $500, Senior Manager $2500) succeed with 200 OK."""
    refund_id = f"ref-bound-{role}"
    mock_repo.seed_record(refund_id, refund_amount=boundary_amount)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": f"Exact boundary approval for {role}."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/refunds/{refund_id}/override",
            json=payload,
            headers={"X-User-Role": role},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approve"
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_agent_denying_any_amount_succeeds(mock_repo: MockTieredRefundRepository):
    """Denials are not constrained by financial approval limits (Agent denying $3,000 succeeds)."""
    mock_repo.seed_record("ref-deny-high", refund_amount=3000.0)
    transport = ASGITransport(app=app)
    payload = {"override_decision": "deny", "reason": "Fraudulent evidence identified."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-deny-high/override",
            json=payload,
            headers={"X-User-Role": "agent"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "deny"
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_manual_escalation_override_sets_senior_manager_tier(
    mock_repo: MockTieredRefundRepository,
):
    """Manual escalation override sets status to 'escalated', decision to 'escalate', and tier to 'senior_manager'."""
    mock_repo.seed_record("ref-esc-test", refund_amount=1500.0)
    transport = ASGITransport(app=app)
    payload = {
        "override_decision": "escalate",
        "reason": "Exceeds supervisor financial authority. Escalating to Senior Manager.",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-esc-test/override",
            json=payload,
            headers={"X-User-Role": "supervisor"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == "ref-esc-test"
    assert data["decision"] == "escalate"
    assert data["status"] == "escalated"
    assert data["escalation_tier"] == "senior_manager"
    assert data["override_decision"] == "escalate"

    stored = mock_repo.get_refund_request("ref-esc-test")
    assert stored is not None
    assert stored.status == "escalated"
    assert stored.escalation_tier == "senior_manager"


@pytest.mark.asyncio
async def test_amount_resolution_falls_back_to_order_amount_and_lookup(
    mock_repo: MockTieredRefundRepository,
):
    """When refund_amount is None, falls back to record.order_amount, then order lookup."""
    # 1. Fall back to order_amount
    mock_repo.seed_record("ref-order-amount-fallback", refund_amount=None, order_amount=180.0)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/refunds/ref-order-amount-fallback/override",
            json={"override_decision": "approve", "reason": "Fallback to order_amount"},
            headers={"X-User-Role": "agent"},
        )
    assert res.status_code == 403
    assert "$180.00" in res.json()["detail"]["detail"]

    # 2. Fall back to mock order data lookup for ORD-1001 (amount $250 in mock_orders.json)
    mock_repo.seed_record(
        "ref-lookup-fallback",
        order_id="ORD-1001",
        refund_amount=None,
        order_amount=None,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res2 = await client.post(
            "/v1/refunds/ref-lookup-fallback/override",
            json={"override_decision": "approve", "reason": "Fallback to order lookup"},
            headers={"X-User-Role": "agent"},
        )
    assert res2.status_code == 403
    assert "$250.00" in res2.json()["detail"]["detail"]


@pytest.mark.asyncio
async def test_jwt_claims_senior_manager_role_integration(mock_repo: MockTieredRefundRepository):
    """JWT bearer token with cognito:groups=['senior_managers'] or ['admin'] resolves to senior_manager role."""
    settings = get_settings()
    token = create_jwt_token(
        payload={"sub": "sm-user-1", "cognito:groups": ["senior_managers"]},
        secret_key=settings.jwt_secret_key,
    )
    mock_repo.seed_record("ref-jwt-sm", refund_amount=2200.0)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-jwt-sm/override",
            json={"override_decision": "approve", "reason": "Senior manager executive signoff"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approve"
    assert data["overridden_by"] == "sm-user-1"


@pytest.mark.asyncio
async def test_unauthorized_role_rejected(mock_repo: MockTieredRefundRepository):
    """Roles other than agent, supervisor, senior_manager are rejected with HTTP 403."""
    mock_repo.seed_record("ref-unauthorized", refund_amount=50.0)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-unauthorized/override",
            json={"override_decision": "approve", "reason": "Unauthorized role"},
            headers={"X-User-Role": "guest"},
        )

    assert response.status_code == 403
    problem = response.json().get("detail", response.json())
    assert problem["status"] == 403
    assert "Authorized operator role required" in problem["detail"]
