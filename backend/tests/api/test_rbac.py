"""Unit and integration tests for role-based access control (RBAC) on refund endpoints."""

from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.auth.rbac import DEFAULT_ROLE, get_current_user_role, require_supervisor_role
from app.db.repository import RefundNotFoundError
from app.main import app
from app.schemas.refund import RefundRecord
from fastapi import HTTPException, Request


class MockRefundRepository:
    """Mock repository for RBAC endpoint testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str = "ORD-9001",
        status: str = "escalated",
        decision: str | None = "escalate",
        reasoning: str | None = "Needs supervisor review",
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
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
        return records[:limit]

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        return self.records.get(refund_id)

    def create_refund_request(
        self, order_id: str, customer_request_text: str
    ) -> RefundRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        refund_id = f"ref_{len(self.records) + 1}"
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

    def apply_override(
        self,
        refund_id: str,
        override_decision: str,
        override_reason: str,
        approval_email_text: str | None = None,
        denial_email_text: str | None = None,
        overridden_by: str | None = "supervisor",
    ) -> RefundRecord:
        record = self.records.get(refund_id)
        if record is None:
            raise RefundNotFoundError(f"Refund request '{refund_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated = record.model_copy(
            update={
                "override_decision": override_decision,
                "override_reason": override_reason,
                "overridden_at": now_iso,
                "overridden_by": overridden_by,
                "updated_at": now_iso,
                "decision": override_decision,
                "status": "completed",
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


# --- Unit Tests for RBAC Dependencies ---


def test_get_current_user_role_defaults_to_agent():
    """Verify get_current_user_role defaults to 'agent' when header is missing or empty."""
    scope = {"type": "http", "headers": []}
    req = Request(scope)
    assert get_current_user_role(req) == "agent"

    # Empty string or whitespace
    scope_blank = {"type": "http", "headers": [(b"x-user-role", b"   ")]}
    assert get_current_user_role(Request(scope_blank)) == "agent"


def test_get_current_user_role_normalizes_case_and_whitespace():
    """Verify get_current_user_role trims whitespace and converts to lowercase."""
    scope = {"type": "http", "headers": [(b"x-user-role", b"  SUPERVISOR  ")]}
    assert get_current_user_role(Request(scope)) == "supervisor"

    scope_agent = {"type": "http", "headers": [(b"x-user-role", b" Agent ")]}
    assert get_current_user_role(Request(scope_agent)) == "agent"


def test_require_supervisor_role_accepts_supervisor():
    """require_supervisor_role returns role string when role is 'supervisor'."""
    assert require_supervisor_role(role="supervisor") == "supervisor"


def test_require_supervisor_role_raises_403_for_non_supervisor():
    """require_supervisor_role raises HTTPException 403 with RFC 9457 structure when role is not supervisor."""
    scope = {"type": "http", "path": "/v1/refunds/ref-1/override", "headers": []}
    req = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        require_supervisor_role(role="agent", request=req)

    assert exc_info.value.status_code == 403
    problem = exc_info.value.detail
    assert isinstance(problem, dict)
    assert problem["status"] == 403
    assert problem["title"] == "Forbidden"
    assert problem["detail"] == "Supervisor role required to perform manual overrides."
    assert problem["type"] == "urn:problem:forbidden"
    assert problem["instance"] == "/v1/refunds/ref-1/override"


# --- API Integration Tests for Manual Override RBAC ---


@pytest.mark.parametrize("endpoint_path", ["/v1/refunds/ref-rbac-1/override", "/refunds/ref-rbac-1/override"])
@pytest.mark.asyncio
async def test_override_missing_role_header_returns_403(
    mock_repo: MockRefundRepository, endpoint_path: str
):
    """Calling override endpoint without X-User-Role header returns 403 Forbidden with RFC 9457 details."""
    mock_repo.seed_record("ref-rbac-1")
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Customer exception granted."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(endpoint_path, json=payload)

    assert response.status_code == 403
    data = response.json()
    problem = data.get("detail", data)
    assert problem["status"] == 403
    assert problem["title"] == "Forbidden"
    assert problem["detail"] == "Supervisor role required to perform manual overrides."
    assert problem["type"] == "urn:problem:forbidden"
    assert endpoint_path in problem["instance"]


@pytest.mark.parametrize(
    "invalid_role",
    ["agent", "AGENT", " agent ", "guest", "admin", "unknown_role", ""],
)
@pytest.mark.asyncio
async def test_override_non_supervisor_role_returns_403(
    mock_repo: MockRefundRepository, invalid_role: str
):
    """Calling override endpoint with non-supervisor role returns 403 Forbidden."""
    mock_repo.seed_record("ref-rbac-1")
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Customer exception granted."}
    headers = {"X-User-Role": invalid_role} if invalid_role else {}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-rbac-1/override", json=payload, headers=headers
        )

    assert response.status_code == 403
    data = response.json()
    problem = data.get("detail", data)
    assert problem["status"] == 403
    assert problem["title"] == "Forbidden"
    assert problem["detail"] == "Supervisor role required to perform manual overrides."
    assert problem["type"] == "urn:problem:forbidden"


@pytest.mark.parametrize(
    "valid_role_header",
    ["supervisor", "SUPERVISOR", " Supervisor ", "  supervisor  "],
)
@pytest.mark.asyncio
async def test_override_supervisor_role_succeeds(
    mock_repo: MockRefundRepository, valid_role_header: str
):
    """Calling override endpoint with supervisor role succeeds and updates record."""
    mock_repo.seed_record("ref-rbac-2")
    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Authorized VIP refund."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-rbac-2/override",
            json=payload,
            headers={"X-User-Role": valid_role_header},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == "ref-rbac-2"
    assert data["decision"] == "approve"
    assert data["status"] == "completed"
    assert data["override_decision"] == "approve"
    assert data["overridden_by"] == "supervisor"


@pytest.mark.asyncio
async def test_override_records_operator_id_from_header(mock_repo: MockRefundRepository):
    """Override endpoint extracts operator ID from X-User-Id header and persists to overridden_by."""
    mock_repo.seed_record("ref-rbac-3")
    transport = ASGITransport(app=app)
    payload = {"override_decision": "deny", "reason": "Evidence shows fraud pattern."}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-rbac-3/override",
            json=payload,
            headers={
                "X-User-Role": "supervisor",
                "X-User-Id": "operator-alice-77",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["overridden_by"] == "operator-alice-77"

    stored = mock_repo.get_refund_request("ref-rbac-3")
    assert stored is not None
    assert stored.overridden_by == "operator-alice-77"


@pytest.mark.asyncio
async def test_override_supervisor_preserves_404_and_422(mock_repo: MockRefundRepository):
    """Supervisor role preserves 404 Not Found and 422 Validation Error behaviors."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 404 on nonexistent record
        res_404 = await client.post(
            "/v1/refunds/nonexistent-id/override",
            json={"override_decision": "approve", "reason": "Valid reason"},
            headers={"X-User-Role": "supervisor"},
        )
        assert res_404.status_code == 404

        # 422 on invalid payload (e.g. empty reason)
        mock_repo.seed_record("ref-rbac-4")
        res_422 = await client.post(
            "/v1/refunds/ref-rbac-4/override",
            json={"override_decision": "approve", "reason": ""},
            headers={"X-User-Role": "supervisor"},
        )
        assert res_422.status_code == 422


# --- Non-Override Endpoints Accessible to All Roles ---


@pytest.mark.parametrize(
    "role_header",
    [None, "agent", "AGENT", "guest"],
)
@pytest.mark.asyncio
async def test_non_override_endpoints_accessible_to_agents(
    mock_repo: MockRefundRepository, role_header: str | None
):
    """GET /refunds, GET /refunds/{id}, and GET /refunds/export remain accessible without supervisor role."""
    mock_repo.seed_record("ref-rbac-5", order_id="ORD-5555")
    transport = ASGITransport(app=app)
    headers = {"X-User-Role": role_header} if role_header else {}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /v1/refunds
        res_list = await client.get("/v1/refunds", headers=headers)
        assert res_list.status_code == 200

        # GET /v1/refunds/{id}
        res_detail = await client.get("/v1/refunds/ref-rbac-5", headers=headers)
        assert res_detail.status_code == 200

        # GET /v1/refunds/export?format=json
        res_export = await client.get("/v1/refunds/export?format=json", headers=headers)
        assert res_export.status_code == 200
