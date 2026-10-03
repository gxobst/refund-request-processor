"""Unit and integration tests for Amazon Cognito and OAuth2 JWT authentication."""

from datetime import datetime, timezone
import time
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository
from app.auth.jwt import (
    _base64url_decode,
    _base64url_encode,
    create_jwt_token,
    decode_jwt,
    extract_user_id,
    extract_user_role,
)
from app.auth.rbac import get_current_user_identity, get_current_user_role, require_supervisor_role
from app.core.config import Settings, get_settings
from app.db.repository import RefundNotFoundError
from app.main import app
from app.schemas.refund import RefundRecord


TEST_SECRET_KEY = "test-jwt-secret-key-32-chars-long!"


class MockRefundRepository:
    """Mock repository for JWT auth endpoint testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str = "ORD-JWT-001",
        status: str = "escalated",
        decision: str | None = "escalate",
        reasoning: str | None = "Needs supervisor review",
        refund_amount: float | None = None,
        order_amount: float | None = None,
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


# --- Unit Tests: Base64URL and JWT Decoding / Verification ---


def test_base64url_encode_and_decode():
    """Verify base64url encoding and decoding round-trip without padding issues."""
    test_cases = [
        b"",
        b"f",
        b"fo",
        b"foo",
        b"foob",
        b"fooba",
        b"foobar",
        b'{"sub":"usr-123","roles":["supervisor"]}',
        b"\x00\xff\xfe\xfd",
    ]
    for raw in test_cases:
        encoded = _base64url_encode(raw)
        assert "=" not in encoded
        assert "+" not in encoded
        assert "/" not in encoded
        decoded = _base64url_decode(encoded)
        assert decoded == raw


def test_create_and_decode_jwt_success():
    """Verify standard JWT token creation and successful decoding."""
    payload = {
        "sub": "user-42",
        "cognito:groups": ["supervisors"],
        "token_use": "id",
    }
    token = create_jwt_token(payload, secret_key=TEST_SECRET_KEY, expires_in=1800)
    decoded = decode_jwt(token, secret_key=TEST_SECRET_KEY)
    assert decoded["sub"] == "user-42"
    assert decoded["cognito:groups"] == ["supervisors"]
    assert decoded["token_use"] == "id"
    assert "exp" in decoded


def test_decode_jwt_invalid_signature():
    """Verify token signed with a different key is rejected with HTTP 401."""
    payload = {"sub": "user-42", "cognito:groups": ["supervisors"]}
    token = create_jwt_token(payload, secret_key="wrong-secret-key-1234567890123")

    with pytest.raises(HTTPException) as exc_info:
        decode_jwt(token, secret_key=TEST_SECRET_KEY)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["status"] == 401
    assert exc_info.value.detail["title"] == "Unauthorized"
    assert exc_info.value.detail["type"] == "urn:problem:unauthorized"
    assert "Invalid or expired" in exc_info.value.detail["detail"]


def test_decode_jwt_expired_token():
    """Verify expired token is rejected with HTTP 401."""
    expired_payload = {
        "sub": "user-expired",
        "cognito:groups": ["supervisors"],
        "exp": int(time.time()) - 120,
    }
    token = create_jwt_token(expired_payload, secret_key=TEST_SECRET_KEY)

    with pytest.raises(HTTPException) as exc_info:
        decode_jwt(token, secret_key=TEST_SECRET_KEY)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["status"] == 401


@pytest.mark.parametrize(
    "malformed_token",
    [
        "",
        "single-part-token",
        "two.parts",
        "four.parts.token.extra",
        "invalid!base64.invalid!payload.sig",
        "e30.e30",  # 2 parts
        "e30.notjson.sig",
    ],
)
def test_decode_jwt_malformed_token(malformed_token: str):
    """Verify malformed tokens raise HTTP 401."""
    with pytest.raises(HTTPException) as exc_info:
        decode_jwt(malformed_token, secret_key=TEST_SECRET_KEY)
    assert exc_info.value.status_code == 401


def test_decode_jwt_token_use_validation():
    """Verify token_use claim must be 'access' or 'id'."""
    valid_access = create_jwt_token({"sub": "u1", "token_use": "access"}, secret_key=TEST_SECRET_KEY)
    valid_id = create_jwt_token({"sub": "u1", "token_use": "id"}, secret_key=TEST_SECRET_KEY)
    invalid_use = create_jwt_token({"sub": "u1", "token_use": "refresh"}, secret_key=TEST_SECRET_KEY)

    assert decode_jwt(valid_access, secret_key=TEST_SECRET_KEY)["token_use"] == "access"
    assert decode_jwt(valid_id, secret_key=TEST_SECRET_KEY)["token_use"] == "id"

    with pytest.raises(HTTPException) as exc_info:
        decode_jwt(invalid_use, secret_key=TEST_SECRET_KEY)
    assert exc_info.value.status_code == 401


def test_decode_jwt_issuer_validation(monkeypatch):
    """Verify iss claim is validated when cognito_user_pool_id is set."""
    custom_settings = Settings(
        cognito_user_pool_id="us-east-1_TestPool",
        aws_region="us-east-1",
        jwt_secret_key=TEST_SECRET_KEY,
    )
    monkeypatch.setattr("app.auth.jwt.get_settings", lambda: custom_settings)

    expected_iss = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"
    token_valid_iss = create_jwt_token({"sub": "u1", "iss": expected_iss}, secret_key=TEST_SECRET_KEY)
    token_mismatched_iss = create_jwt_token({"sub": "u1", "iss": "https://attacker.example.com"}, secret_key=TEST_SECRET_KEY)

    # Valid issuer passes
    decoded = decode_jwt(token_valid_iss, secret_key=TEST_SECRET_KEY)
    assert decoded["iss"] == expected_iss

    # Mismatched issuer raises 401
    with pytest.raises(HTTPException) as exc_info:
        decode_jwt(token_mismatched_iss, secret_key=TEST_SECRET_KEY)
    assert exc_info.value.status_code == 401


# --- Unit Tests: Role & Identity Extraction ---


@pytest.mark.parametrize(
    "payload, expected_role",
    [
        ({"cognito:groups": ["supervisors"]}, "supervisor"),
        ({"cognito:groups": ["admin"]}, "senior_manager"),
        ({"cognito:groups": ["senior_managers"]}, "senior_manager"),
        ({"cognito:groups": ["senior_manager"]}, "senior_manager"),
        ({"cognito:groups": ["supervisor"]}, "supervisor"),
        ({"cognito:groups": ["SUPERVISORS"]}, "supervisor"),
        ({"cognito:groups": ["agents", "supervisors"]}, "supervisor"),
        ({"cognito:groups": ["agents", "senior_managers"]}, "senior_manager"),
        ({"roles": ["admin"]}, "senior_manager"),
        ({"roles": ["supervisor"]}, "supervisor"),
        ({"cognito:groups": ["agents"]}, "agent"),
        ({"cognito:groups": []}, "agent"),
        ({"roles": ["agent"]}, "agent"),
        ({}, "agent"),
        ({"cognito:groups": "supervisor"}, "supervisor"),
        ({"cognito:groups": "senior_manager"}, "senior_manager"),
        ({"cognito:groups": "agent"}, "agent"),
    ],
)
def test_extract_user_role(payload: dict, expected_role: str):
    """Verify role resolution for various Cognito groups and roles claims."""
    assert extract_user_role(payload) == expected_role


@pytest.mark.parametrize(
    "payload, expected_id",
    [
        ({"sub": "cognito-sub-1234"}, "cognito-sub-1234"),
        ({"cognito:username": "janedoe"}, "janedoe"),
        ({"username": "johnsmith"}, "johnsmith"),
        ({"sub": "sub-1", "cognito:username": "user-1"}, "sub-1"),
        ({}, "anonymous"),
    ],
)
def test_extract_user_id(payload: dict, expected_id: str):
    """Verify user identity resolution from sub, cognito:username, or username."""
    assert extract_user_id(payload) == expected_id


# --- Unit Tests: RBAC Request Handlers ---


def test_get_current_user_identity_from_bearer_token(monkeypatch):
    """get_current_user_identity reads user sub from Bearer token."""
    monkeypatch.setattr("app.auth.jwt.get_settings", lambda: Settings(jwt_secret_key=TEST_SECRET_KEY))
    token = create_jwt_token({"sub": "usr-supervisor-99", "cognito:groups": ["supervisors"]}, secret_key=TEST_SECRET_KEY)

    scope = {
        "type": "http",
        "path": "/test",
        "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
    }
    req = Request(scope)
    identity = get_current_user_identity(req)
    assert identity == "usr-supervisor-99"


def test_get_current_user_identity_fallback_to_headers():
    """get_current_user_identity falls back to X-User-Id and X-User-Role when Authorization is absent."""
    # With X-User-Id
    scope_id = {
        "type": "http",
        "path": "/test",
        "headers": [(b"x-user-id", b"custom-agent-007")],
    }
    assert get_current_user_identity(Request(scope_id)) == "custom-agent-007"

    # Fallback to X-User-Role supervisor
    scope_role = {
        "type": "http",
        "path": "/test",
        "headers": [(b"x-user-role", b"supervisor")],
    }
    assert get_current_user_identity(Request(scope_role)) == "supervisor"

    # Fallback to default agent
    scope_empty = {"type": "http", "path": "/test", "headers": []}
    assert get_current_user_identity(Request(scope_empty)) == "agent"


def test_auth_require_jwt_enforcement(monkeypatch):
    """When auth_require_jwt is True, missing Authorization raises HTTP 401."""
    custom_settings = Settings(auth_require_jwt=True, jwt_secret_key=TEST_SECRET_KEY)
    monkeypatch.setattr("app.auth.rbac.get_settings", lambda: custom_settings)

    scope = {
        "type": "http",
        "path": "/v1/refunds/ref-1/override",
        "headers": [(b"x-user-role", b"supervisor")],
    }
    req = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_role(req)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["status"] == 401
    assert exc_info.value.detail["detail"] == "Authorization header required"


# --- API Integration Tests with Bearer Tokens ---


@pytest.mark.asyncio
async def test_override_with_supervisor_bearer_token_succeeds(
    mock_repo: MockRefundRepository, monkeypatch
):
    """Supervisor Bearer token authorizes manual override and records identity in overridden_by."""
    monkeypatch.setattr("app.auth.jwt.get_settings", lambda: Settings(jwt_secret_key=TEST_SECRET_KEY))
    mock_repo.seed_record("ref-jwt-1")

    token = create_jwt_token(
        {"sub": "supervisor-sub-001", "cognito:groups": ["supervisors"]},
        secret_key=TEST_SECRET_KEY,
    )

    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Customer exception granted."}
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-jwt-1/override", json=payload, headers=headers
        )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == "ref-jwt-1"
    assert data["decision"] == "approve"
    assert data["overridden_by"] == "supervisor-sub-001"


@pytest.mark.asyncio
async def test_override_with_agent_bearer_token_returns_403(
    mock_repo: MockRefundRepository, monkeypatch
):
    """Agent Bearer token receives HTTP 403 Forbidden with RFC 9457 ProblemDetails."""
    monkeypatch.setattr("app.auth.jwt.get_settings", lambda: Settings(jwt_secret_key=TEST_SECRET_KEY))
    mock_repo.seed_record("ref-jwt-2", refund_amount=250.0)

    token = create_jwt_token(
        {"sub": "agent-sub-002", "cognito:groups": ["agents"]},
        secret_key=TEST_SECRET_KEY,
    )

    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Should fail"}
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-jwt-2/override", json=payload, headers=headers
        )

    assert response.status_code == 403
    problem = response.json().get("detail", response.json())
    assert problem["status"] == 403
    assert problem["title"] == "Forbidden"
    assert problem["type"] == "urn:problem:forbidden"


@pytest.mark.asyncio
async def test_override_with_invalid_signature_bearer_token_returns_401(
    mock_repo: MockRefundRepository, monkeypatch
):
    """Bearer token with invalid signature returns HTTP 401 Unauthorized ProblemDetails."""
    monkeypatch.setattr("app.auth.jwt.get_settings", lambda: Settings(jwt_secret_key=TEST_SECRET_KEY))
    mock_repo.seed_record("ref-jwt-3")

    token = create_jwt_token(
        {"sub": "attacker", "cognito:groups": ["supervisors"]},
        secret_key="tampered-secret-key-signature",
    )

    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Attack attempt"}
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-jwt-3/override", json=payload, headers=headers
        )

    assert response.status_code == 401
    problem = response.json().get("detail", response.json())
    assert problem["status"] == 401
    assert problem["title"] == "Unauthorized"
    assert problem["type"] == "urn:problem:unauthorized"


@pytest.mark.asyncio
async def test_override_with_expired_bearer_token_returns_401(
    mock_repo: MockRefundRepository, monkeypatch
):
    """Expired Bearer token returns HTTP 401 Unauthorized ProblemDetails."""
    monkeypatch.setattr("app.auth.jwt.get_settings", lambda: Settings(jwt_secret_key=TEST_SECRET_KEY))
    mock_repo.seed_record("ref-jwt-4")

    token = create_jwt_token(
        {"sub": "supervisor-expired", "cognito:groups": ["supervisors"], "exp": int(time.time()) - 300},
        secret_key=TEST_SECRET_KEY,
    )

    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Expired token"}
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-jwt-4/override", json=payload, headers=headers
        )

    assert response.status_code == 401
    problem = response.json().get("detail", response.json())
    assert problem["status"] == 401
    assert problem["title"] == "Unauthorized"


@pytest.mark.asyncio
async def test_override_with_malformed_bearer_token_returns_401(
    mock_repo: MockRefundRepository, monkeypatch
):
    """Malformed Bearer token returns HTTP 401 Unauthorized ProblemDetails."""
    monkeypatch.setattr("app.auth.jwt.get_settings", lambda: Settings(jwt_secret_key=TEST_SECRET_KEY))
    mock_repo.seed_record("ref-jwt-5")

    transport = ASGITransport(app=app)
    payload = {"override_decision": "approve", "reason": "Malformed"}
    headers = {"Authorization": "Bearer not-a-valid-jwt-token"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-jwt-5/override", json=payload, headers=headers
        )

    assert response.status_code == 401
    problem = response.json().get("detail", response.json())
    assert problem["status"] == 401
    assert problem["title"] == "Unauthorized"


@pytest.mark.asyncio
async def test_backward_compatibility_x_user_role_still_works(
    mock_repo: MockRefundRepository, monkeypatch
):
    """When Authorization is omitted and auth_require_jwt=False, X-User-Role still functions seamlessly."""
    monkeypatch.setattr("app.auth.rbac.get_settings", lambda: Settings(auth_require_jwt=False))
    mock_repo.seed_record("ref-compat-1")

    transport = ASGITransport(app=app)
    payload = {"override_decision": "deny", "reason": "Policy violation confirmed"}
    headers = {"X-User-Role": "supervisor", "X-User-Id": "legacy-supervisor-88"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/refunds/ref-compat-1/override", json=payload, headers=headers
        )

    assert response.status_code == 200
    data = response.json()
    assert data["overridden_by"] == "legacy-supervisor-88"
    assert data["decision"] == "deny"
