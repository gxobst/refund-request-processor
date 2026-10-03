"""Unit and API integration tests for real-time policy configuration updates via Server-Sent Events (SSE)."""

import asyncio
import json
from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.policy.loader import reset_active_policies
from app.services.broadcaster import broadcaster


@pytest.fixture(autouse=True)
def cleanup_state():
    """Ensure in-memory policy rules and broadcaster subscribers are restored after every test."""
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
async def test_put_policy_v1_emits_policy_update_event(client: AsyncClient):
    """PUT /v1/policies/{category} broadcasts a policy_update event with full configuration."""
    queue = await broadcaster.subscribe()
    try:
        payload = {
            "return_window_days": 45,
            "max_refund_amount": 750.0,
            "auto_approve_threshold": 100.0,
            "requires_proof": True,
        }
        response = await client.put("/v1/policies/damaged", json=payload)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["category"] == "damaged"
        assert resp_data["return_window_days"] == 45
        assert resp_data["max_refund_amount"] == 750.0
        assert resp_data["auto_approve_threshold"] == 100.0
        assert resp_data["requires_proof"] is True

        event_msg = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert event_msg["event"] == "policy_update"
        data = event_msg["data"]
        assert data["category"] == "damaged"
        assert data["return_window_days"] == 45
        assert data["max_refund_amount"] == 750.0
        assert data["auto_approve_threshold"] == 100.0
        assert data["requires_proof"] is True
        assert data["eligible_delivery_statuses"] == ["delivered"]
        assert data["refund_window_days"] == 45
        assert data["max_order_amount"] == 750.0
    finally:
        await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_put_policy_without_prefix_emits_policy_update_event(client: AsyncClient):
    """PUT /policies/{category} (unprefixed) broadcasts a policy_update event."""
    queue = await broadcaster.subscribe()
    try:
        payload = {
            "return_window_days": 21,
            "max_refund_amount": 350.0,
        }
        response = await client.put("/policies/changed_mind", json=payload)
        assert response.status_code == 200

        event_msg = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert event_msg["event"] == "policy_update"
        data = event_msg["data"]
        assert data["category"] == "changed_mind"
        assert data["return_window_days"] == 21
        assert data["max_refund_amount"] == 350.0
        assert data["refund_window_days"] == 21
        assert data["max_order_amount"] == 350.0
    finally:
        await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_put_policy_streaming_sse_client_receives_event(client: AsyncClient):
    """Connected SSE client on GET /v1/refunds/events receives formatted policy_update SSE event."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as sse_client:
        async def perform_put():
            await asyncio.sleep(0.05)
            put_res = await client.put(
                "/v1/policies/wrong_item",
                json={"return_window_days": 60, "max_refund_amount": 1200.0},
            )
            assert put_res.status_code == 200

        task = asyncio.create_task(perform_put())
        sse_response = await sse_client.get("/v1/refunds/events?limit=2")
        await task

        assert sse_response.status_code == 200
        text = sse_response.text
        assert "event: ping" in text
        assert "event: policy_update" in text
        assert "wrong_item" in text
        assert "1200.0" in text or "1200" in text


@pytest.mark.asyncio
async def test_put_policy_streaming_sse_unprefixed_endpoint_receives_event(client: AsyncClient):
    """Connected SSE client on GET /refunds/events receives policy_update SSE event."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as sse_client:
        async def perform_put():
            await asyncio.sleep(0.05)
            put_res = await client.put(
                "/policies/missing_item",
                json={"return_window_days": 40},
            )
            assert put_res.status_code == 200

        task = asyncio.create_task(perform_put())
        sse_response = await sse_client.get("/refunds/events?limit=2")
        await task

        assert sse_response.status_code == 200
        text = sse_response.text
        assert "event: policy_update" in text
        assert "missing_item" in text


@pytest.mark.asyncio
async def test_invalid_category_returns_404_and_does_not_publish_event(client: AsyncClient):
    """PUT with unknown category returns 404 and does not emit any SSE event."""
    queue = await broadcaster.subscribe()
    try:
        response = await client.put(
            "/v1/policies/unknown_category",
            json={"return_window_days": 30},
        )
        assert response.status_code == 404
        assert queue.empty()
    finally:
        await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_validation_error_returns_422_and_does_not_publish_event(client: AsyncClient):
    """PUT with invalid field values returns 422 and does not emit any SSE event."""
    queue = await broadcaster.subscribe()
    try:
        # Negative return window
        res1 = await client.put(
            "/v1/policies/damaged",
            json={"return_window_days": -1},
        )
        assert res1.status_code == 422
        assert queue.empty()

        # Negative max refund amount
        res2 = await client.put(
            "/v1/policies/damaged",
            json={"max_refund_amount": -100.0},
        )
        assert res2.status_code == 422
        assert queue.empty()

        # Non-dict body
        res3 = await client.put(
            "/v1/policies/damaged",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert res3.status_code == 422
        assert queue.empty()
    finally:
        await broadcaster.unsubscribe(queue)
