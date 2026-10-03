"""Unit and API integration tests for policy configuration version history and audit log rollback."""

import asyncio
from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.policy.loader import (
    get_active_policies,
    get_policy_history,
    reset_active_policies,
    rollback_policy,
)
from app.services.broadcaster import broadcaster


@pytest.fixture(autouse=True)
def restore_policies_and_broadcaster():
    """Ensure in-memory policies, audit history, and broadcaster are cleaned after every test."""
    reset_active_policies()
    broadcaster._subscribers.clear()
    yield
    reset_active_policies()
    broadcaster._subscribers.clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_update_policy_records_audit_entry_with_diffs_and_snapshot(client: AsyncClient):
    """PUT /v1/policies/{category} records an audit entry with diffs, previous snapshot, and operator_id."""
    headers = {"X-User-Id": "operator-42"}
    payload = {
        "return_window_days": 45,
        "max_refund_amount": 750.0,
    }

    res = await client.put("/v1/policies/damaged", json=payload, headers=headers)
    assert res.status_code == 200

    history_res = await client.get("/v1/policies/history")
    assert history_res.status_code == 200
    entries = history_res.json()
    assert len(entries) == 1

    entry = entries[0]
    assert entry["audit_id"].startswith("audit_")
    assert entry["category"] == "damaged"
    assert entry["operator_id"] == "operator-42"
    assert entry["action"] == "update"
    assert "timestamp" in entry

    # Previous state snapshot
    assert entry["previous_state"]["return_window_days"] == 30
    assert entry["previous_state"]["max_refund_amount"] == 500.0

    # Field change diffs
    assert "return_window_days" in entry["changes"]
    assert entry["changes"]["return_window_days"]["old_value"] == 30
    assert entry["changes"]["return_window_days"]["new_value"] == 45

    assert "max_refund_amount" in entry["changes"]
    assert entry["changes"]["max_refund_amount"]["old_value"] == 500.0
    assert entry["changes"]["max_refund_amount"]["new_value"] == 750.0


@pytest.mark.asyncio
async def test_operator_id_fallback_to_user_role_and_default(client: AsyncClient):
    """Operator ID extracts from X-User-Id, falls back to X-User-Role, and defaults to 'supervisor'."""
    # 1. Fallback to X-User-Role
    res1 = await client.put(
        "/v1/policies/changed_mind",
        json={"return_window_days": 20},
        headers={"X-User-Role": "admin"},
    )
    assert res1.status_code == 200

    # 2. Default to 'supervisor' when no headers provided
    res2 = await client.put(
        "/v1/policies/wrong_item",
        json={"return_window_days": 40},
    )
    assert res2.status_code == 200

    history = (await client.get("/v1/policies/history")).json()
    assert len(history) == 2
    # Reverse chronological order: wrong_item was last
    assert history[0]["category"] == "wrong_item"
    assert history[0]["operator_id"] == "supervisor"
    assert history[1]["category"] == "changed_mind"
    assert history[1]["operator_id"] == "admin"


@pytest.mark.asyncio
async def test_get_history_ordering_and_category_filtering(client: AsyncClient):
    """GET /v1/policies/history and GET /policies/history return reverse-chronological logs and filter by category."""
    # Create 3 modifications across different categories
    await client.put("/v1/policies/damaged", json={"return_window_days": 35})
    await client.put("/v1/policies/late_delivery", json={"return_window_days": 20})
    await client.put("/v1/policies/damaged", json={"return_window_days": 40})

    # Test all history on both endpoints
    for endpoint in ("/v1/policies/history", "/policies/history"):
        res = await client.get(endpoint)
        assert res.status_code == 200
        entries = res.json()
        assert len(entries) == 3
        # Newest first
        assert entries[0]["category"] == "damaged"
        assert entries[0]["changes"]["return_window_days"]["new_value"] == 40
        assert entries[1]["category"] == "late_delivery"
        assert entries[2]["category"] == "damaged"
        assert entries[2]["changes"]["return_window_days"]["new_value"] == 35

    # Filter by category damaged
    res_damaged = await client.get("/v1/policies/history?category=damaged")
    assert res_damaged.status_code == 200
    damaged_entries = res_damaged.json()
    assert len(damaged_entries) == 2
    assert all(e["category"] == "damaged" for e in damaged_entries)
    assert damaged_entries[0]["changes"]["return_window_days"]["new_value"] == 40
    assert damaged_entries[1]["changes"]["return_window_days"]["new_value"] == 35

    # Filter by category late_delivery
    res_late = await client.get("/policies/history?category=late_delivery")
    assert res_late.status_code == 200
    late_entries = res_late.json()
    assert len(late_entries) == 1
    assert late_entries[0]["category"] == "late_delivery"


@pytest.mark.asyncio
async def test_get_history_returns_404_for_unknown_category(client: AsyncClient):
    """GET /v1/policies/history?category=unknown returns RFC 9457 ProblemDetails 404."""
    for endpoint in ("/v1/policies/history?category=invalid_category", "/policies/history?category=invalid_category"):
        res = await client.get(endpoint)
        assert res.status_code == 404
        assert res.headers["content-type"] == "application/problem+json"
        body = res.json()
        assert body["type"] == "urn:problem:not-found"
        assert body["title"] == "Not Found"
        assert "invalid_category" in body["detail"]


@pytest.mark.asyncio
async def test_rollback_policy_restores_immediate_predecessor_and_broadcasts_sse(client: AsyncClient):
    """POST /v1/policies/{category}/rollback restores predecessor state and broadcasts policy_update SSE event."""
    queue = await broadcaster.subscribe()
    try:
        # Initial update
        put_res = await client.put(
            "/v1/policies/damaged",
            json={"return_window_days": 55, "max_refund_amount": 900.0},
            headers={"X-User-Id": "operator-editor"},
        )
        assert put_res.status_code == 200

        # Drain initial put event from broadcaster
        put_event = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert put_event["event"] == "policy_update"

        # Rollback without specifying audit_id
        rollback_res = await client.post(
            "/v1/policies/damaged/rollback",
            headers={"X-User-Id": "supervisor-reverter"},
        )
        assert rollback_res.status_code == 200
        restored = rollback_res.json()
        assert restored["category"] == "damaged"
        assert restored["return_window_days"] == 30
        assert restored["max_refund_amount"] == 500.0

        # Verify active policy reflects restoration
        active_res = await client.get("/v1/policies")
        active_items = {item["category"]: item for item in active_res.json()}
        assert active_items["damaged"]["return_window_days"] == 30
        assert active_items["damaged"]["max_refund_amount"] == 500.0

        # Verify broadcaster received policy_update event for rollback
        rb_event = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert rb_event["event"] == "policy_update"
        assert rb_event["data"]["category"] == "damaged"
        assert rb_event["data"]["return_window_days"] == 30

        # Verify audit history records rollback entry
        history_res = await client.get("/v1/policies/history?category=damaged")
        history = history_res.json()
        assert len(history) == 2
        rollback_entry = history[0]
        assert rollback_entry["action"] == "rollback"
        assert rollback_entry["operator_id"] == "supervisor-reverter"
        assert rollback_entry["changes"]["return_window_days"]["old_value"] == 55
        assert rollback_entry["changes"]["return_window_days"]["new_value"] == 30
    finally:
        await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_rollback_policy_with_specific_audit_id_query_and_body(client: AsyncClient):
    """POST /v1/policies/{category}/rollback can target a specific audit_id via query param or JSON body."""
    # 1. Update from 30 -> 40
    await client.put("/v1/policies/missing_item", json={"return_window_days": 40})
    history1 = (await client.get("/v1/policies/history?category=missing_item")).json()
    first_audit_id = history1[0]["audit_id"]

    # 2. Update from 40 -> 60
    await client.put("/v1/policies/missing_item", json={"return_window_days": 60})

    # Current value is 60
    assert get_active_policies().missing_item.return_window_days == 60

    # 3. Rollback specifically to first update's previous_state (30 days) via query param
    rb_res = await client.post(f"/v1/policies/missing_item/rollback?audit_id={first_audit_id}")
    assert rb_res.status_code == 200
    assert rb_res.json()["return_window_days"] == 30
    assert get_active_policies().missing_item.return_window_days == 30

    # 4. Now update again to 75
    await client.put("/v1/policies/missing_item", json={"return_window_days": 75})
    history2 = (await client.get("/v1/policies/history?category=missing_item")).json()
    update_audit_id = history2[0]["audit_id"]

    # 5. Rollback via JSON body
    rb_res_body = await client.post(
        "/policies/missing_item/rollback",
        json={"audit_id": update_audit_id},
    )
    assert rb_res_body.status_code == 200
    assert rb_res_body.json()["return_window_days"] == 30


@pytest.mark.asyncio
async def test_rollback_policy_error_cases_return_404_problem_details(client: AsyncClient):
    """POST /v1/policies/{category}/rollback returns 404 ProblemDetails for invalid category, missing history, or unknown audit_id."""
    # 1. Unknown category
    res1 = await client.post("/v1/policies/unknown_category/rollback")
    assert res1.status_code == 404
    assert res1.headers["content-type"] == "application/problem+json"
    body1 = res1.json()
    assert body1["type"] == "urn:problem:not-found"
    assert "unknown_category" in body1["detail"]

    # 2. Known category but no history exists to rollback
    res2 = await client.post("/v1/policies/wrong_item/rollback")
    assert res2.status_code == 404
    assert res2.headers["content-type"] == "application/problem+json"
    body2 = res2.json()
    assert body2["type"] == "urn:problem:not-found"
    assert "wrong_item" in body2["detail"]

    # 3. Known category with history, but nonexistent audit_id specified
    await client.put("/v1/policies/wrong_item", json={"return_window_days": 45})
    res3 = await client.post("/v1/policies/wrong_item/rollback?audit_id=audit_invalid_123")
    assert res3.status_code == 404
    body3 = res3.json()
    assert body3["type"] == "urn:problem:not-found"
    assert "audit_invalid_123" in body3["detail"]


@pytest.mark.asyncio
async def test_reset_active_policies_clears_audit_history():
    """reset_active_policies() restores defaults and resets audit history to empty."""
    from app.policy.loader import update_category_policy

    update_category_policy("damaged", {"return_window_days": 90})
    assert len(get_policy_history()) == 1

    reset_active_policies()
    assert len(get_policy_history()) == 0
    assert get_active_policies().damaged.return_window_days == 30
