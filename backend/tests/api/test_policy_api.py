"""Unit and integration tests for policy viewer and administrative configuration API."""

from datetime import date
from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.policy.engine import evaluate_policy
from app.policy.loader import get_active_policies, reset_active_policies


@pytest.fixture(autouse=True)
def restore_policies_after_test():
    """Ensure in-memory policy rules are restored to defaults after every test."""
    reset_active_policies()
    yield
    reset_active_policies()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_policies_returns_all_five_categories(client: AsyncClient):
    """GET /v1/policies and GET /policies return active rules for all 5 categories."""
    for endpoint in ("/v1/policies", "/policies"):
        response = await client.get(endpoint)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 5

        categories = [item["category"] for item in data]
        assert categories == ["damaged", "wrong_item", "changed_mind", "late_delivery", "missing_item"]

        for item in data:
            assert "category" in item
            assert "return_window_days" in item
            assert item["return_window_days"] > 0
            assert "max_refund_amount" in item
            assert item["max_refund_amount"] >= 0.0
            assert "auto_approve_threshold" in item
            assert item["auto_approve_threshold"] >= 0.0
            assert "requires_proof" in item
            assert isinstance(item["requires_proof"], bool)
            assert "eligible_delivery_statuses" in item
            assert len(item["eligible_delivery_statuses"]) >= 1
            # Backward-compatible aliases
            assert item["refund_window_days"] == item["return_window_days"]
            assert item["max_order_amount"] == item["max_refund_amount"]


@pytest.mark.asyncio
async def test_put_policy_updates_category_rules(client: AsyncClient):
    """PUT /v1/policies/{category} updates rules and subsequent GET reflects changes."""
    update_payload = {
        "return_window_days": 45,
        "max_refund_amount": 750.0,
        "auto_approve_threshold": 50.0,
        "requires_proof": True,
        "eligible_delivery_statuses": ["delivered", "signed"],
    }

    put_res = await client.put("/v1/policies/damaged", json=update_payload)
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["category"] == "damaged"
    assert updated["return_window_days"] == 45
    assert updated["max_refund_amount"] == 750.0
    assert updated["auto_approve_threshold"] == 50.0
    assert updated["requires_proof"] is True
    assert updated["eligible_delivery_statuses"] == ["delivered", "signed"]
    assert updated["refund_window_days"] == 45
    assert updated["max_order_amount"] == 750.0

    # Verify GET reflects the changes
    get_res = await client.get("/v1/policies")
    assert get_res.status_code == 200
    items = {item["category"]: item for item in get_res.json()}
    damaged_item = items["damaged"]
    assert damaged_item["return_window_days"] == 45
    assert damaged_item["max_refund_amount"] == 750.0
    assert damaged_item["auto_approve_threshold"] == 50.0
    assert damaged_item["requires_proof"] is True


@pytest.mark.asyncio
async def test_put_policy_at_root_url_updates_successfully(client: AsyncClient):
    """PUT /policies/{category} at root prefix also updates successfully."""
    update_payload = {
        "return_window_days": 21,
        "max_refund_amount": 400.0,
    }
    put_res = await client.put("/policies/changed_mind", json=update_payload)
    assert put_res.status_code == 200
    data = put_res.json()
    assert data["category"] == "changed_mind"
    assert data["return_window_days"] == 21
    assert data["max_refund_amount"] == 400.0


@pytest.mark.asyncio
async def test_engine_immediately_uses_updated_thresholds(client: AsyncClient):
    """Deterministic evaluation engine immediately uses updated active thresholds without restart."""
    today_iso = date.today().isoformat()
    order_data = {
        "order_id": "ORD-9999",
        "order_amount": 600.0,
        "delivery_status": "delivered",
        "delivery_date": today_iso,
    }

    # Default max_order_amount for damaged is 500.0 -> order of $600 exceeds threshold
    initial_res = evaluate_policy(category="damaged", order=order_data)
    assert initial_res.status == "ambiguous"
    assert "max_order_amount" in initial_res.failed_rules

    # Operator raises max_refund_amount to 800.0 via API
    put_res = await client.put("/v1/policies/damaged", json={"max_refund_amount": 800.0})
    assert put_res.status_code == 200

    # Subsequent evaluation immediately passes with no restart or custom config passed
    updated_res = evaluate_policy(category="damaged", order=order_data)
    assert updated_res.status == "pass"
    assert "max_order_amount" in updated_res.passed_rules
    assert not updated_res.failed_rules


@pytest.mark.asyncio
async def test_put_policy_returns_404_for_unknown_category(client: AsyncClient):
    """PUT /v1/policies/{category} returns RFC 9457 ProblemDetails 404 for invalid category."""
    response = await client.put(
        "/v1/policies/unknown_category",
        json={"return_window_days": 30},
    )
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "urn:problem:not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert "unknown_category" in body["detail"]
    assert body["instance"] == "/v1/policies/unknown_category"


@pytest.mark.asyncio
async def test_put_policy_returns_422_for_negative_or_zero_values(client: AsyncClient):
    """PUT /v1/policies/{category} returns RFC 9457 ValidationProblemDetails 422 for invalid inputs."""
    invalid_cases = [
        {"return_window_days": 0},
        {"return_window_days": -10},
        {"max_refund_amount": -5.0},
        {"auto_approve_threshold": -1.0},
        {"eligible_delivery_statuses": []},
    ]

    for payload in invalid_cases:
        res = await client.put("/v1/policies/damaged", json=payload)
        assert res.status_code == 422
        assert res.headers["content-type"] == "application/problem+json"
        body = res.json()
        assert body["type"] == "urn:problem:validation-error"
        assert body["title"] == "Validation Error"
        assert body["status"] == 422
        assert "invalidParams" in body
        assert len(body["invalidParams"]) > 0


@pytest.mark.asyncio
async def test_put_policy_with_non_dict_body_returns_422(client: AsyncClient):
    """PUT /v1/policies/{category} returns 422 when body is not a JSON object."""
    res = await client.put(
        "/v1/policies/damaged",
        content="not-json",
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["type"] == "urn:problem:validation-error"


@pytest.mark.asyncio
async def test_reset_active_policies_restores_defaults():
    """reset_active_policies() resets active memory state to file defaults."""
    get_active_policies().damaged.return_window_days = 999
    assert get_active_policies().damaged.return_window_days == 999

    reset_active_policies()
    assert get_active_policies().damaged.return_window_days == 30
