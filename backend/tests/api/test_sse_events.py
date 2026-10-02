"""Unit and API integration tests for Server-Sent Events (SSE) streaming and event broadcasting."""

import asyncio
import json
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import get_repository, subscribe_refund_events
from app.graph.nodes import record_decision_node, save_dynamo_node
from app.main import app
from app.schemas.refund import RefundRecord
from app.services.broadcaster import EventBroadcaster, broadcaster


class MockRefundRepository:
    """Mock repository for SSE testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def create_refund_request(
        self,
        order_id: str,
        customer_request_text: str,
        evidence: list | None = None,
    ) -> RefundRecord:
        record = RefundRecord(
            refund_id="ref_sse_test_1",
            order_id=order_id,
            customer_request_text=customer_request_text,
            status="pending",
            created_at="2026-10-02T12:00:00Z",
            updated_at="2026-10-02T12:00:00Z",
            evidence=evidence or [],
        )
        self.records[record.refund_id] = record
        return record

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        return self.records.get(refund_id)

    def apply_override(
        self,
        refund_id: str,
        override_decision: str,
        override_reason: str,
    ) -> RefundRecord:
        rec = self.records[refund_id]
        rec.status = "completed"
        rec.override_decision = override_decision
        rec.reasoning = override_reason
        return rec

    def submit_clarification_response(
        self,
        refund_id: str,
        clarification_response: str,
    ) -> RefundRecord:
        rec = self.records[refund_id]
        rec.status = "pending"
        rec.clarification_response = clarification_response
        return rec

    def request_reviewer_proof(
        self,
        refund_id: str,
        proof_prompt: str,
        notification_email_text: str,
    ) -> RefundRecord:
        rec = self.records[refund_id]
        rec.status = "awaiting_clarification"
        return rec

    def update_decision(
        self,
        refund_id: str,
        decision: str,
        reasoning: str,
        matched_policy_rule: dict | None = None,
        confidence_score: float = 0.0,
        status: str = "completed",
        **kwargs,
    ) -> RefundRecord:
        rec = self.records[refund_id]
        rec.status = status
        rec.decision = decision
        rec.reasoning = reasoning
        rec.confidence_score = confidence_score
        return rec


@pytest.fixture(autouse=True)
def reset_broadcaster():
    """Ensure broadcaster subscribers are clean between tests."""
    broadcaster._subscribers.clear()
    yield
    broadcaster._subscribers.clear()


@pytest.mark.asyncio
async def test_event_broadcaster_pub_sub():
    """Test EventBroadcaster in-memory pub/sub behavior directly."""
    bc = EventBroadcaster()
    queue = await bc.subscribe()
    assert bc.subscriber_count == 1

    delivered = await bc.publish("refund_update", {"refund_id": "ref_1", "status": "pending"})
    assert delivered == 1

    item = await queue.get()
    assert item["event"] == "refund_update"
    assert item["data"]["refund_id"] == "ref_1"
    assert item["data"]["status"] == "pending"

    await bc.unsubscribe(queue)
    assert bc.subscriber_count == 0


@pytest.mark.asyncio
async def test_event_broadcaster_queue_full_cleanup():
    """Test broadcaster drops events for full queues and handles multiple subscribers."""
    bc = EventBroadcaster(max_queue_size=1)
    q1 = await bc.subscribe()
    q2 = await bc.subscribe()
    assert bc.subscriber_count == 2

    # Fill q1 to its limit
    await bc.publish("event1", {"n": 1})
    # Second publish when q1 is full
    await bc.publish("event2", {"n": 2})

    item1 = q1.get_nowait()
    assert item1["event"] == "event1"
    assert q1.empty()

    await bc.unsubscribe(q1)
    await bc.unsubscribe(q2)
    assert bc.subscriber_count == 0


@pytest.mark.asyncio
async def test_sse_endpoint_headers_and_initial_ping():
    """Test GET /v1/refunds/events returns text/event-stream with initial connection ping."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/refunds/events?limit=1")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert response.headers.get("cache-control") == "no-cache"
        assert response.headers.get("connection") == "keep-alive"

        text = response.text
        assert "event: ping" in text
        assert "data: {}" in text


@pytest.mark.asyncio
async def test_sse_endpoint_both_route_prefixes():
    """Test SSE endpoint works at both /v1/refunds/events and /refunds/events."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for path in ("/v1/refunds/events?limit=1", "/refunds/events?limit=1"):
            response = await client.get(path)
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_sse_stream_receives_published_events():
    """Test that connected SSE client receives broadcasted refund_update events."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Schedule publishing right after connection establishes
        async def delayed_publish():
            await asyncio.sleep(0.05)
            await broadcaster.publish(
                "refund_update",
                {"refund_id": "ref_live_123", "order_id": "ORD-1001", "status": "pending"},
            )

        task = asyncio.create_task(delayed_publish())
        response = await client.get("/v1/refunds/events?limit=2")
        await task

        assert response.status_code == 200
        text = response.text
        assert "event: ping" in text
        assert "event: refund_update" in text
        assert "ref_live_123" in text
        assert "pending" in text


@pytest.mark.asyncio
async def test_post_refunds_publishes_creation_event(monkeypatch: pytest.MonkeyPatch):
    """Test POST /v1/refunds publishes refund_update event containing refund_id, order_id, status: pending."""
    from unittest.mock import AsyncMock
    monkeypatch.setattr("app.api.refunds.run_refund_workflow", AsyncMock())

    mock_repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: mock_repo

    queue = await broadcaster.subscribe()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/v1/refunds",
                json={"order_id": "ORD-1001", "customer_request_text": "Item damaged on arrival"},
            )
            assert res.status_code == 202
            refund_id = res.json()["refund_id"]

            item = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert item["event"] == "refund_update"
            assert item["data"]["refund_id"] == refund_id
            assert item["data"]["order_id"] == "ORD-1001"
            assert item["data"]["status"] == "pending"
    finally:
        app.dependency_overrides.pop(get_repository, None)
        await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_post_override_publishes_event():
    """Test POST /v1/refunds/{id}/override publishes refund_update with override_decision and reasoning."""
    mock_repo = MockRefundRepository()
    mock_repo.records["ref_override_1"] = RefundRecord(
        refund_id="ref_override_1",
        order_id="ORD-1002",
        customer_request_text="Sample request",
        status="escalated",
        created_at="2026-10-02T12:00:00Z",
        updated_at="2026-10-02T12:00:00Z",
    )
    app.dependency_overrides[get_repository] = lambda: mock_repo

    queue = await broadcaster.subscribe()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            override_res = await client.post(
                "/v1/refunds/ref_override_1/override",
                json={"override_decision": "approve", "reason": "Customer is a high-value VIP."},
            )
            assert override_res.status_code == 200

            item = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert item["event"] == "refund_update"
            assert item["data"]["refund_id"] == "ref_override_1"
            assert item["data"]["override_decision"] == "approve"
            assert item["data"]["reasoning"] == "Customer is a high-value VIP."
            assert item["data"]["status"] == "completed"
    finally:
        app.dependency_overrides.pop(get_repository, None)
        await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_post_clarify_and_request_proof_publish_events(monkeypatch: pytest.MonkeyPatch):
    """Test clarify and request-proof endpoints publish refund_update events."""
    from unittest.mock import AsyncMock
    monkeypatch.setattr("app.api.refunds.resume_refund_workflow", AsyncMock())

    mock_repo = MockRefundRepository()
    mock_repo.records["ref_clarify_1"] = RefundRecord(
        refund_id="ref_clarify_1",
        order_id="ORD-1003",
        customer_request_text="Need clarification",
        status="awaiting_clarification",
        created_at="2026-10-02T12:00:00Z",
        updated_at="2026-10-02T12:00:00Z",
    )
    mock_repo.records["ref_proof_1"] = RefundRecord(
        refund_id="ref_proof_1",
        order_id="ORD-1004",
        customer_request_text="Escalated refund",
        status="escalated",
        created_at="2026-10-02T12:00:00Z",
        updated_at="2026-10-02T12:00:00Z",
    )
    app.dependency_overrides[get_repository] = lambda: mock_repo

    queue = await broadcaster.subscribe()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Clarify
            clarify_res = await client.post(
                "/v1/refunds/ref_clarify_1/clarify",
                json={"response_text": "Here is more info."},
            )
            assert clarify_res.status_code == 200

            item = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert item["event"] == "refund_update"
            assert item["data"]["refund_id"] == "ref_clarify_1"
            assert item["data"]["status"] == "pending"

            # 2. Request proof
            proof_res = await client.post(
                "/v1/refunds/ref_proof_1/request-proof",
                json={"proof_prompt": "Please attach clear picture", "customer_name": "Alice"},
            )
            assert proof_res.status_code == 200

            item2 = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert item2["event"] == "refund_update"
            assert item2["data"]["refund_id"] == "ref_proof_1"
            assert item2["data"]["status"] == "awaiting_clarification"
    finally:
        app.dependency_overrides.pop(get_repository, None)
        await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_record_decision_node_publishes_decision_event():
    """Test record_decision_node broadcasts refund_update with decision, reasoning, confidence."""
    mock_repo = MockRefundRepository()
    mock_repo.records["ref_dec_1"] = RefundRecord(
        refund_id="ref_dec_1",
        order_id="ORD-1005",
        customer_request_text="Decision test",
        status="pending",
        created_at="2026-10-02T12:00:00Z",
        updated_at="2026-10-02T12:00:00Z",
    )

    queue = await broadcaster.subscribe()

    state = {
        "refund_id": "ref_dec_1",
        "order_id": "ORD-1005",
        "decision": "auto_approve",
        "reasoning": "Within policy limits.",
        "confidence_score": 0.95,
        "status": "completed",
        "_repository": mock_repo,
    }

    result = record_decision_node(state)
    assert result["status"] == "completed"

    # Wait for the async task to deliver
    item = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert item["event"] == "refund_update"
    assert item["data"]["refund_id"] == "ref_dec_1"
    assert item["data"]["order_id"] == "ORD-1005"
    assert item["data"]["decision"] == "auto_approve"
    assert item["data"]["reasoning"] == "Within policy limits."
    assert item["data"]["confidence_score"] == 0.95

    await broadcaster.unsubscribe(queue)


@pytest.mark.asyncio
async def test_sse_disconnect_cleans_up_subscriber():
    """Test subscriber queue is discarded and deregistered when client disconnects or stream closes."""
    assert broadcaster.subscriber_count == 0

    req = MagicMock()
    response = await subscribe_refund_events(req)
    gen = response.body_iterator

    # Read first event (initial ping)
    first_chunk = await anext(gen)
    assert "event: ping" in first_chunk
    assert broadcaster.subscriber_count == 1

    # Simulate client closing/disconnecting the stream
    await gen.aclose()
    assert broadcaster.subscriber_count == 0
