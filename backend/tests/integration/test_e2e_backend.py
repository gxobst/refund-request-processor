"""End-to-end integration tests for backend refund processing lifecycle.

Tests the complete flow from order seeding, API intake, multi-agent evaluation,
status polling, manual override, queue listing, and LangSmith tracing.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
import pytest

from pathlib import Path

from app.api.refunds import get_repository
from app.core.config import Settings
from app.db.repository import RefundRepository
from app.db.seed import seed_orders
from app.graph.runner import run_refund_workflow
from app.main import app
from app.schemas.classifier import ClassificationOutput
from app.schemas.policy_checker import PolicyCheckerOutput
from app.schemas.refund import RefundRecord
from app.services.storage import EvidenceStorageService, get_evidence_storage_service


# --- In-Memory DynamoDB Mock Components for Offline Integration Testing ---


class MockBatchWriter:
    """Mock DynamoDB batch_writer context manager."""

    def __init__(self, table: "MockDynamoTable") -> None:
        self.table = table

    def __enter__(self) -> "MockBatchWriter":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def put_item(self, Item: dict[str, Any]) -> None:
        key = Item.get("refund_id") or Item.get("order_id")
        if key:
            self.table.items[key] = Item


class MockDynamoTable:
    """Mock DynamoDB Table supporting orders and refund requests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.items: dict[str, dict[str, Any]] = {}

    def batch_writer(self) -> MockBatchWriter:
        return MockBatchWriter(self)

    def put_item(self, Item: dict[str, Any]) -> dict[str, Any]:
        key = Item.get("refund_id") or Item.get("order_id")
        if key:
            self.items[key] = Item
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_item(self, Key: dict[str, Any]) -> dict[str, Any]:
        key = Key.get("refund_id") or Key.get("order_id")
        item = self.items.get(key)
        if item is not None:
            return {"Item": item}
        return {}

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        return {"Items": list(self.items.values())}


class MockDynamoResource:
    """Mock boto3 DynamoDB resource."""

    def __init__(self) -> None:
        self.tables: dict[str, MockDynamoTable] = {}

    def Table(self, name: str) -> MockDynamoTable:
        if name not in self.tables:
            self.tables[name] = MockDynamoTable(name)
        return self.tables[name]


# --- Fixtures ---


@pytest.fixture
def mock_dynamo_resource() -> MockDynamoResource:
    """Provide a clean mock DynamoDB resource for tests."""
    return MockDynamoResource()


@pytest.fixture
def mock_repo(mock_dynamo_resource: MockDynamoResource) -> RefundRepository:
    """Provide a real RefundRepository backed by an in-memory DynamoDB resource."""
    repo = RefundRepository(
        dynamodb_resource=mock_dynamo_resource, table_name="test_refund_requests"
    )
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.clear()


def _classify_text_to_output(text: str) -> ClassificationOutput:
    t = text.lower()
    eval_text = t.split("[clarification]:")[-1] if "[clarification]:" in t else t
    if "low confidence" in eval_text or "unsure" in eval_text:
        return ClassificationOutput(
            category="damaged",
            confidence_score=0.52,
            reasoning="Low confidence classification due to ambiguous customer wording.",
        )
    elif "wrong item" in eval_text or "incorrect" in eval_text:
        return ClassificationOutput(
            category="wrong_item",
            confidence_score=0.94,
            reasoning="Customer received incorrect item.",
        )
    elif "changed mind" in eval_text or "changed my mind" in eval_text or "mistake" in eval_text:
        return ClassificationOutput(
            category="changed_mind",
            confidence_score=0.91,
            reasoning="Customer changed mind or ordered mistakenly.",
        )
    elif "late" in eval_text or "delay" in eval_text:
        return ClassificationOutput(
            category="late_delivery",
            confidence_score=0.95,
            reasoning="Customer reported late or delayed delivery.",
        )
    else:
        return ClassificationOutput(
            category="damaged",
            confidence_score=0.96,
            reasoning="Customer reported damaged item with clear evidence.",
        )


@pytest.fixture(autouse=True)
def mock_classifier_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock get_bedrock_llm and classify_refund_request for offline deterministic execution."""

    def _mock_classify(text: str, *args: Any, **kwargs: Any) -> ClassificationOutput:
        return _classify_text_to_output(text)

    monkeypatch.setattr("app.agents.classifier.classify_refund_request", _mock_classify)

    def _make_mock_model():
        mock_model = MagicMock()

        def _structured_output(schema):
            def _invoke(inputs):
                if hasattr(inputs, "to_string"):
                    raw_text = inputs.to_string()
                elif hasattr(inputs, "messages"):
                    raw_text = " ".join(str(m.content) for m in inputs.messages)
                elif isinstance(inputs, dict):
                    raw_text = inputs.get("text", "")
                else:
                    raw_text = str(inputs)
                return _classify_text_to_output(raw_text)

            return RunnableLambda(_invoke)

        mock_model.with_structured_output.side_effect = _structured_output
        return mock_model

    monkeypatch.setattr("app.agents.classifier.get_bedrock_llm", _make_mock_model)


# --- Polling Helper ---


async def poll_until_not_pending(
    client: AsyncClient, refund_id: str, max_attempts: int = 15, interval: float = 0.02
) -> dict[str, Any]:
    """Poll GET /refunds/{id} until workflow execution finishes and status is not pending."""
    for _ in range(max_attempts):
        response = await client.get(f"/refunds/{refund_id}")
        assert response.status_code == 200
        data = response.json()
        if data.get("status") != "pending":
            return data
        await asyncio.sleep(interval)
    return response.json()


# --- Tests ---


def test_seed_orders_data_verification(mock_dynamo_resource: MockDynamoResource):
    """AC 1 & 8: Verify seed_orders populates mock orders correctly and they can be retrieved."""
    # Arrange & Act
    seeded_count = seed_orders(
        table_name="mock-orders", dynamodb_resource=mock_dynamo_resource
    )

    # Assert: verify count matches mock_orders.json (10 orders)
    assert seeded_count == 10
    table = mock_dynamo_resource.Table("mock-orders")
    assert len(table.items) == 10

    # Verify retrieval and structure of key records
    ord_1001 = table.items.get("ORD-1001")
    assert ord_1001 is not None
    assert ord_1001["order_id"] == "ORD-1001"
    assert ord_1001["item"] == "Ergonomic Office Chair"
    assert ord_1001["order_amount"] == Decimal("250.0")
    assert ord_1001["delivery_status"] == "delivered"
    assert ord_1001["delivery_date"] == "2026-09-12"

    ord_1003 = table.items.get("ORD-1003")
    assert ord_1003 is not None
    assert ord_1003["item"] == "Ultra-Wide Gaming Monitor"
    assert ord_1003["order_amount"] == Decimal("750.0")

    ord_1005 = table.items.get("ORD-1005")
    assert ord_1005 is not None
    assert ord_1005["delivery_status"] == "in_transit"
    assert "delivery_date" not in ord_1005  # null delivery date excluded from dynamo item

    ord_1008 = table.items.get("ORD-1008")
    assert ord_1008 is not None
    assert ord_1008["order_id"] == "ORD-1008"
    assert ord_1008["item"] == "Smart Fitness Watch"
    assert ord_1008["order_amount"] == Decimal("99.0")
    assert ord_1008["delivery_status"] == "delivered"
    assert ord_1008["delivery_date"] == "2026-09-14"

    ord_1009 = table.items.get("ORD-1009")
    assert ord_1009 is not None
    assert ord_1009["order_id"] == "ORD-1009"
    assert ord_1009["item"] == "Wireless Earbuds"
    assert ord_1009["order_amount"] == Decimal("60.0")
    assert ord_1009["delivery_status"] == "delivered"
    assert ord_1009["delivery_date"] == "2026-09-13"

    ord_1010 = table.items.get("ORD-1010")
    assert ord_1010 is not None
    assert ord_1010["order_id"] == "ORD-1010"
    assert ord_1010["item"] == "Professional Mirrorless Camera"
    assert ord_1010["order_amount"] == Decimal("450.0")
    assert ord_1010["delivery_status"] == "delivered"
    assert ord_1010["delivery_date"] == "2026-09-18"


@pytest.mark.asyncio
async def test_e2e_auto_approve_flow(mock_repo: RefundRepository):
    """AC 2: Verify full lifecycle for valid auto-approved refund request."""
    # Arrange: ORD-1001 is delivered within window, $250 <= $1000 limit for wrong_item category
    payload = {
        "order_id": "ORD-1001",
        "customer_request_text": "I received the wrong item in my package, not the chair I ordered.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Act 1: Submit refund request
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        post_data = post_response.json()
        refund_id = post_data["refund_id"]
        assert refund_id.startswith("ref_")
        assert post_data["order_id"] == "ORD-1001"

        # Act 2: Poll status until workflow finishes
        final_record = await poll_until_not_pending(client, refund_id)

    # Assert: evaluate against success criteria
    assert final_record["status"] == "completed"
    assert final_record["decision"] == "auto_approve"
    assert final_record["confidence_score"] is not None
    assert final_record["confidence_score"] >= 0.7
    assert len(final_record["reasoning"]) > 0
    assert final_record["matched_policy_rule"] is not None
    assert final_record["matched_policy_rule"]["max_order_amount"] == 1000.0


@pytest.mark.asyncio
async def test_e2e_deny_flow(mock_repo: RefundRepository):
    """AC 3: Verify full lifecycle for denied refund request violating policy limits."""
    # Arrange: ORD-1004 has an expired delivery date (August 2026, > 30 days)
    payload = {
        "order_id": "ORD-1004",
        "customer_request_text": "The keyboard switch broke.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        refund_id = post_response.json()["refund_id"]

        final_record = await poll_until_not_pending(client, refund_id)

    # Assert: decision is deny, status is completed, with failure reasoning
    assert final_record["status"] == "completed"
    assert final_record["decision"] == "deny"
    assert len(final_record["reasoning"]) > 0
    assert "denied" in final_record["reasoning"].lower()
    assert final_record["matched_policy_rule"] is not None


@pytest.mark.asyncio
async def test_e2e_escalation_flow_missing_order_data(mock_repo: RefundRepository):
    """AC 4: Verify escalation triggered on missing order data (unknown order ID)."""
    # Arrange: ORD-9999 does not exist in mock_orders.json
    payload = {
        "order_id": "ORD-9999",
        "customer_request_text": "Item arrived broken and I want a refund.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        refund_id = post_response.json()["refund_id"]

        final_record = await poll_until_not_pending(client, refund_id)

    # Assert: status is escalated, decision is escalate
    assert final_record["status"] == "escalated"
    assert final_record["decision"] == "escalate"
    assert "missing" in final_record["reasoning"].lower() or "order" in final_record["reasoning"].lower()


@pytest.mark.asyncio
async def test_e2e_escalation_flow_low_confidence(mock_repo: RefundRepository):
    """AC 4: Verify escalation triggered when classifier confidence is low and clarification cycles are exhausted."""
    # Arrange: text triggers low confidence in mock classifier
    payload = {
        "order_id": "ORD-1001",
        "customer_request_text": "I am unsure what happened, low confidence description of problem.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Initial submission pauses at awaiting_clarification (cycle 1)
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        refund_id = post_response.json()["refund_id"]

        clarify_1 = await poll_until_not_pending(client, refund_id)
        assert clarify_1["status"] == "awaiting_clarification"
        assert clarify_1["clarification_count"] == 1
        assert clarify_1["category"] is not None
        assert clarify_1["confidence_score"] is not None
        assert clarify_1["confidence_score"] < 0.70
        assert clarify_1["reasoning"] is not None
        assert clarify_1["decision"] is None

        # Step 2: Customer provides still-ambiguous clarification (cycle 2)
        res1 = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": "Still unsure about what happened, low confidence info."},
        )
        assert res1.status_code == 200

        clarify_2 = await poll_until_not_pending(client, refund_id)
        assert clarify_2["status"] == "awaiting_clarification"
        assert clarify_2["clarification_count"] == 2

        # Step 3: Customer provides clarification a second time (exhausts 2 attempts, routes to decision)
        res2 = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": "Still unsure and low confidence."},
        )
        assert res2.status_code == 200

        final_record = await poll_until_not_pending(client, refund_id)

    # Assert: escalated after max clarification cycles exhausted
    assert final_record["status"] == "escalated"
    assert final_record["decision"] == "escalate"
    assert "confidence" in final_record["reasoning"].lower()


@pytest.mark.asyncio
async def test_e2e_clarification_lifecycle(mock_repo: RefundRepository):
    """Verify end-to-end customer clarification lifecycle from pause to resumption and auto-approval."""
    payload = {
        "order_id": "ORD-1001",
        "customer_request_text": "I am unsure what happened, low confidence description.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Submit ambiguous refund request
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        refund_id = post_response.json()["refund_id"]

        # 2. Poll until workflow pauses at awaiting_clarification
        paused_record = await poll_until_not_pending(client, refund_id)
        assert paused_record["status"] == "awaiting_clarification"
        assert paused_record["clarification_count"] == 1
        assert paused_record["clarification_prompt"] is not None
        assert paused_record["category"] is not None
        assert paused_record["confidence_score"] is not None
        assert paused_record["confidence_score"] < 0.70
        assert paused_record["reasoning"] is not None
        assert len(paused_record["reasoning"]) > 0
        assert paused_record["decision"] is None

        # 3. Customer submits clarification response via POST /refunds/{refund_id}/clarify
        clarify_payload = {
            "response_text": "I received the wrong item in my package, it was not the ergonomic chair I ordered.",
        }
        clarify_response = await client.post(
            f"/refunds/{refund_id}/clarify", json=clarify_payload
        )
        assert clarify_response.status_code == 200
        clarify_data = clarify_response.json()
        assert clarify_data["status"] == "pending"
        assert clarify_data["clarification_response"] == clarify_payload["response_text"]

        # 4. Background workflow resumes, poll until completed
        final_record = await poll_until_not_pending(client, refund_id)

    assert final_record["status"] == "completed"
    assert final_record["decision"] == "auto_approve"
    assert final_record["confidence_score"] >= 0.70
    assert final_record["clarification_response"] == clarify_payload["response_text"]
    assert "wrong_item" in final_record["reasoning"].lower() or "approved" in final_record["reasoning"].lower()


@pytest.mark.asyncio
async def test_e2e_clarification_lifecycle_ord_1008(mock_repo: RefundRepository):
    """AC 1650 & 1651: Verify end-to-end customer clarification lifecycle for ORD-1008 from pause to auto-approval."""
    payload = {
        "order_id": "ORD-1008",
        "customer_request_text": "I am unsure what happened, low confidence description of problem with fitness watch.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Initial intake evaluates to confidence < 0.70 and pauses at awaiting_clarification
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        refund_id = post_response.json()["refund_id"]

        paused_record = await poll_until_not_pending(client, refund_id)
        assert paused_record["status"] == "awaiting_clarification"
        assert paused_record["clarification_count"] == 1
        assert paused_record["clarification_prompt"] is not None
        assert paused_record["category"] is not None
        assert paused_record["confidence_score"] is not None
        assert paused_record["confidence_score"] < 0.70
        assert paused_record["reasoning"] is not None
        assert len(paused_record["reasoning"]) > 0
        assert paused_record["decision"] is None

        # Step 2: Customer submits high-confidence clarifying response via POST /refunds/{refund_id}/clarify
        clarify_payload = {
            "response_text": "I received the wrong item, an incorrect fitness watch model, different color and version than ordered.",
        }
        clarify_response = await client.post(
            f"/refunds/{refund_id}/clarify", json=clarify_payload
        )
        assert clarify_response.status_code == 200
        clarify_data = clarify_response.json()
        assert clarify_data["status"] == "pending"
        assert clarify_data["clarification_response"] == clarify_payload["response_text"]

        # Step 3: Background workflow resumes, re-evaluates with confidence >= 0.70, and completes
        final_record = await poll_until_not_pending(client, refund_id)

    assert final_record["status"] == "completed"
    assert final_record["decision"] == "auto_approve"
    assert final_record["confidence_score"] >= 0.70
    assert final_record["clarification_response"] == clarify_payload["response_text"]
    assert "wrong_item" in final_record["reasoning"].lower() or "approved" in final_record["reasoning"].lower()


@pytest.mark.asyncio
async def test_e2e_clarification_exhaustion_escalates_ord_1009(mock_repo: RefundRepository):
    """AC 1652: Verify that repeated ambiguous clarification responses for ORD-1009 exhaust cycles and escalate."""
    payload = {
        "order_id": "ORD-1009",
        "customer_request_text": "I am unsure what happened, low confidence description of wireless earbuds.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Cycle 1: initial submission pauses at awaiting_clarification
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        refund_id = post_response.json()["refund_id"]

        clarify_1 = await poll_until_not_pending(client, refund_id)
        assert clarify_1["status"] == "awaiting_clarification"
        assert clarify_1["clarification_count"] == 1
        assert clarify_1["clarification_prompt"] is not None

        # Cycle 2: first ambiguous clarification response
        res1 = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": "Still unsure about what happened, low confidence details."},
        )
        assert res1.status_code == 200

        clarify_2 = await poll_until_not_pending(client, refund_id)
        assert clarify_2["status"] == "awaiting_clarification"
        assert clarify_2["clarification_count"] == 2

        # Cycle 3: second ambiguous clarification response (exhausts max cycles >= 2)
        res2 = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": "Still unsure and low confidence description."},
        )
        assert res2.status_code == 200

        final_record = await poll_until_not_pending(client, refund_id)

    assert final_record["status"] == "escalated"
    assert final_record["decision"] == "escalate"
    assert "confidence" in final_record["reasoning"].lower() or "clarification" in final_record["reasoning"].lower()


@pytest.mark.asyncio
async def test_e2e_high_confidence_requests_bypass_clarification(mock_repo: RefundRepository):
    """AC 1653: Verify high-confidence refund requests for ORD-1001 and ORD-1003 bypass clarification."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. ORD-1001 with high confidence request text
        res_1001 = await client.post(
            "/refunds",
            json={
                "order_id": "ORD-1001",
                "customer_request_text": "I received the wrong item in my package, not the ergonomic chair I ordered.",
            },
        )
        assert res_1001.status_code == 202
        ref_id_1001 = res_1001.json()["refund_id"]

        record_1001 = await poll_until_not_pending(client, ref_id_1001)
        assert record_1001["status"] == "completed"
        assert record_1001["decision"] == "auto_approve"
        assert record_1001["confidence_score"] >= 0.70
        assert record_1001["clarification_count"] == 0
        assert record_1001["clarification_prompt"] is None

        # 2. ORD-1010 with high confidence request text (exceeds max_order_amount, escalates immediately without clarification)
        res_1010 = await client.post(
            "/refunds",
            json={
                "order_id": "ORD-1010",
                "customer_request_text": "I changed my mind about this mirrorless camera and would like a refund.",
            },
        )
        assert res_1010.status_code == 202
        ref_id_1010 = res_1010.json()["refund_id"]

        record_1010 = await poll_until_not_pending(client, ref_id_1010)
        assert record_1010["status"] == "escalated"
        assert record_1010["decision"] == "escalate"
        assert record_1010["confidence_score"] >= 0.70
        assert record_1010["clarification_count"] == 0
        assert record_1010["clarification_prompt"] is None


@pytest.mark.asyncio
async def test_e2e_override_flow(mock_repo: RefundRepository):
    """AC 5: Verify human operator override on an escalated refund request."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Submit request that will escalate
        create_res = await client.post(
            "/refunds",
            json={
                "order_id": "ORD-9999",
                "customer_request_text": "Missing order details request.",
            },
        )
        assert create_res.status_code == 202
        refund_id = create_res.json()["refund_id"]

        # Step 2: Poll until escalated
        escalated_record = await poll_until_not_pending(client, refund_id)
        assert escalated_record["status"] == "escalated"
        assert escalated_record["decision"] == "escalate"

        # Step 3: Apply manual override via POST /refunds/{id}/override
        override_payload = {
            "override_decision": "approve",
            "reason": "Customer VIP status verified in external CRM. Exception granted by supervisor.",
        }
        override_res = await client.post(
            f"/refunds/{refund_id}/override", json=override_payload
        )
        assert override_res.status_code == 200
        override_data = override_res.json()

        # Assert: updated to completed with operator decision and reasoning
        assert override_data["refund_id"] == refund_id
        assert override_data["status"] == "completed"
        assert override_data["decision"] == "approve"
        assert override_data["override_decision"] == "approve"
        assert override_data["override_reason"] == override_payload["reason"]
        assert override_data["overridden_at"] is not None

        # Step 4: Verify subsequent GET /refunds/{id} reflects the updated state
        poll_res = await client.get(f"/refunds/{refund_id}")
        assert poll_res.status_code == 200
        poll_data = poll_res.json()
        assert poll_data["decision"] == "approve"
        assert poll_data["status"] == "completed"
        assert poll_data["override_reason"] == override_payload["reason"]


@pytest.mark.asyncio
async def test_e2e_queue_listing_and_filtering(mock_repo: RefundRepository):
    """Verify queue listing endpoint returns all requests and filters accurately."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Submit 1 auto-approved request
        r1 = await client.post(
            "/refunds",
            json={"order_id": "ORD-1001", "customer_request_text": "Wrong item received."},
        )
        # Submit 1 denied request
        r2 = await client.post(
            "/refunds",
            json={"order_id": "ORD-1004", "customer_request_text": "Keyboard broken."},
        )
        # Submit 1 escalated request
        r3 = await client.post(
            "/refunds",
            json={"order_id": "ORD-9999", "customer_request_text": "Missing order."},
        )

        id1, id2, id3 = (
            r1.json()["refund_id"],
            r2.json()["refund_id"],
            r3.json()["refund_id"],
        )

        await poll_until_not_pending(client, id1)
        await poll_until_not_pending(client, id2)
        await poll_until_not_pending(client, id3)

        # Act & Assert 1: List all
        all_res = await client.get("/refunds")
        assert all_res.status_code == 200
        all_data = all_res.json()
        returned_ids = {item["refund_id"] for item in all_data}
        assert id1 in returned_ids
        assert id2 in returned_ids
        assert id3 in returned_ids

        # Act & Assert 2: Filter completed
        completed_res = await client.get("/refunds?status=completed")
        assert completed_res.status_code == 200
        completed_ids = {item["refund_id"] for item in completed_res.json()}
        assert id1 in completed_ids
        assert id2 in completed_ids
        assert id3 not in completed_ids

        # Act & Assert 3: Filter escalated
        escalated_res = await client.get("/refunds?status=escalated")
        assert escalated_res.status_code == 200
        escalated_ids = {item["refund_id"] for item in escalated_res.json()}
        assert id3 in escalated_ids
        assert id1 not in escalated_ids
        assert id2 not in escalated_ids


class SpyingCallbackHandler(BaseCallbackHandler):
    """Callback handler verifying LangSmith tracing metadata and span emissions."""

    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.ends: list[dict[str, Any]] = []

    def on_chain_start(
        self, serialized: dict[str, Any], inputs: dict[str, Any], **kwargs: Any
    ) -> None:
        self.starts.append({"serialized": serialized, "inputs": inputs, "kwargs": kwargs})

    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> None:
        self.ends.append({"outputs": outputs, "kwargs": kwargs})


@pytest.mark.asyncio
async def test_langsmith_observability_tracing(monkeypatch: pytest.MonkeyPatch):
    """AC 9: Verify LangSmith configuration and span/metadata emissions when tracing is active."""
    # Arrange: set LangSmith environment variables
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_integration_test_key_123")
    monkeypatch.setenv("LANGSMITH_PROJECT", "refund-request-processor")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")

    settings = Settings(_env_file=None)
    assert settings.langsmith_tracing is True
    assert settings.langsmith_project == "refund-request-processor"
    assert settings.langsmith_api_key == "lsv2_pt_integration_test_key_123"

    # Arrange: attach a tracing callback spy to run_refund_workflow execution
    spy_handler = SpyingCallbackHandler()
    checkpointer_mock = MagicMock()
    checkpointer_mock.aget_tuple.return_value = None
    checkpointer_mock.aput.return_value = {}

    # Act: execute workflow with tracing callback
    result = await run_refund_workflow(
        refund_id="ref_trace_test_100",
        order_id="ORD-1001",
        customer_request_text="Wrong item received with tracing enabled.",
        thread_id="thread_trace_100",
        callbacks=[spy_handler],
    )

    # Assert: result is completed and workflow ran
    assert result["status"] == "completed"
    assert result["decision"] == "auto_approve"
    assert result["refund_id"] == "ref_trace_test_100"

    # Verify tracing callback captured execution and attached metadata
    assert len(spy_handler.starts) > 0
    root_start = spy_handler.starts[0]
    meta = root_start.get("kwargs", {}).get("metadata", {})
    assert meta.get("refund_id") == "ref_trace_test_100"
    assert meta.get("order_id") == "ORD-1001"
    tags = root_start.get("kwargs", {}).get("tags", [])
    assert "refund-workflow" in tags


class MockToolCallingModel:
    """Mock LLM supporting tool binding and structured output for policy checker."""

    def __init__(
        self, responses: list[AIMessage], final_output: PolicyCheckerOutput
    ) -> None:
        self.responses = list(responses)
        self.final_output = final_output

    def bind_tools(self, tools: list[Any]) -> "MockToolCallingModel":
        return self

    def invoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        if self.responses:
            return self.responses.pop(0)
        json_str = (
            self.final_output.model_dump_json()
            if hasattr(self.final_output, "model_dump_json")
            else ""
        )
        return AIMessage(content=f"```json\n{json_str}\n```", tool_calls=[])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return RunnableLambda(lambda _: self.final_output)


@pytest.mark.asyncio
async def test_e2e_tool_calling_audit_log_persisted_and_exposed(
    mock_repo: RefundRepository, monkeypatch: pytest.MonkeyPatch
):
    """Verify end-to-end workflow run with tool calling records tool_calls in state, persists to DynamoDB, and exposes via GET /refunds/{id}."""
    # Arrange: mock policy checker LLM to trigger carrier tool invocation for ORD-1005
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1005"},
            "id": "call_e2e_trk_1005",
        }],
    )
    expected_policy_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Carrier tracking confirmed shipment delayed in transit past expected delivery date.",
    )
    mock_policy_llm = MockToolCallingModel(
        responses=[tool_call_msg], final_output=expected_policy_output
    )
    monkeypatch.setattr(
        "app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm
    )

    payload = {
        "order_id": "ORD-1005",
        "customer_request_text": "My package delivery is delayed and very late. Tracking number TRK-1005.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Submit refund request
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        # 2. Poll status until completed
        final_record = await poll_until_not_pending(client, refund_id)

        # 3. Direct GET endpoint check
        get_res = await client.get(f"/refunds/{refund_id}")
        assert get_res.status_code == 200
        record_data = get_res.json()

    # Assert
    assert final_record["status"] == "completed"
    assert final_record["decision"] == "auto_approve"
    assert "tool_calls" in final_record
    assert len(final_record["tool_calls"]) == 1

    audit_entry = final_record["tool_calls"][0]
    assert audit_entry["tool_name"] == "query_carrier_tracking"
    assert audit_entry["tool_call_id"] == "call_e2e_trk_1005"
    assert audit_entry["tool_input"] == {"tracking_number": "TRK-1005"}
    assert audit_entry["tool_output"]["found"] is True
    assert audit_entry["tool_output"]["carrier"] == "FedEx"
    assert audit_entry["tool_output"]["delivery_status"] == "in_transit"
    assert "timestamp" in audit_entry

    # Verify DynamoDB repository record
    db_record = mock_repo.get_refund_request(refund_id)
    assert db_record is not None
    assert len(db_record.tool_calls) == 1
    assert db_record.tool_calls[0]["tool_name"] == "query_carrier_tracking"

    # Verify GET response exposed tool_calls
    assert len(record_data["tool_calls"]) == 1
    assert record_data["tool_calls"][0]["tool_name"] == "query_carrier_tracking"


@pytest.mark.asyncio
async def test_e2e_dual_tool_verification_flow_ord_1010(
    mock_repo: RefundRepository, monkeypatch: pytest.MonkeyPatch
):
    """Verify end-to-end workflow run for high-value order ORD-1010 executing both carrier and payment tools, storing both audit records in DynamoDB."""
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "query_carrier_tracking",
                "args": {"tracking_number": "TRK-1010"},
                "id": "call_e2e_trk_1010",
            },
            {
                "name": "query_payment_transaction",
                "args": {"order_id": "ORD-1010"},
                "id": "call_e2e_pay_1010",
            },
        ],
    )
    expected_policy_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Carrier delivery confirmed with proof photo and Stripe transaction succeeded with refund eligibility.",
    )
    mock_policy_llm = MockToolCallingModel(
        responses=[tool_call_msg], final_output=expected_policy_output
    )
    monkeypatch.setattr(
        "app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm
    )

    payload = {
        "order_id": "ORD-1010",
        "customer_request_text": "High value mirrorless camera received was the wrong item.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Submit refund request
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        # 2. Poll status until completed
        final_record = await poll_until_not_pending(client, refund_id)

        # 3. Direct GET endpoint check
        get_res = await client.get(f"/refunds/{refund_id}")
        assert get_res.status_code == 200
        record_data = get_res.json()

    # Assert: workflow state and response
    assert final_record["status"] == "completed"
    assert final_record["decision"] == "auto_approve"
    assert "tool_calls" in final_record
    assert len(final_record["tool_calls"]) == 2

    tool_names = [t["tool_name"] for t in final_record["tool_calls"]]
    assert "query_carrier_tracking" in tool_names
    assert "query_payment_transaction" in tool_names

    carrier_call = next(t for t in final_record["tool_calls"] if t["tool_name"] == "query_carrier_tracking")
    assert carrier_call["tool_output"]["found"] is True
    assert carrier_call["tool_output"]["carrier"] == "FedEx"
    assert carrier_call["tool_output"]["proof_of_delivery_photo_available"] is True

    payment_call = next(t for t in final_record["tool_calls"] if t["tool_name"] == "query_payment_transaction")
    assert payment_call["tool_output"]["found"] is True
    assert payment_call["tool_output"]["charge_amount"] == 450.0
    assert payment_call["tool_output"]["refund_eligibility"] is True

    # Verify DynamoDB persistence storing both tool call audit records
    db_record = mock_repo.get_refund_request(refund_id)
    assert db_record is not None
    assert len(db_record.tool_calls) == 2
    db_tool_names = [t["tool_name"] for t in db_record.tool_calls]
    assert "query_carrier_tracking" in db_tool_names
    assert "query_payment_transaction" in db_tool_names

    # Verify GET response exposed tool_calls
    assert len(record_data["tool_calls"]) == 2


@pytest.mark.asyncio
async def test_e2e_reviewer_proof_request_and_clarification_resumption(
    mock_repo: RefundRepository, tmp_path: Path
):
    """Verify an escalated refund transitioned to awaiting_clarification via request-proof accepts evidence and clarification, resuming workflow."""
    storage_service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    app.dependency_overrides[get_evidence_storage_service] = lambda: storage_service

    payload = {
        "order_id": "ORD-1010",
        "customer_request_text": "I changed my mind about this mirrorless camera and want to return it.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Submit request and poll until escalated
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        escalated_record = await poll_until_not_pending(client, refund_id)
        assert escalated_record["status"] == "escalated"
        assert escalated_record["decision"] == "escalate"

        # Step 2: Reviewer requests proof via POST /refunds/{refund_id}/request-proof
        proof_payload = {
            "proof_prompt": "Please provide a clear photo of the cracked screen and product barcode.",
            "customer_name": "Marcus Vance",
        }
        proof_res = await client.post(
            f"/refunds/{refund_id}/request-proof", json=proof_payload
        )
        assert proof_res.status_code == 200
        proof_data = proof_res.json()
        assert proof_data["status"] == "awaiting_clarification"
        assert proof_data["decision"] is None
        assert proof_data["clarification_prompt"] == proof_payload["proof_prompt"]
        assert "Dear Marcus Vance," in proof_data["clarification_email_text"]
        assert "Supervisor Inquiry:" in proof_data["clarification_email_text"]
        assert "JPEG, PNG, or WebP" in proof_data["clarification_email_text"]

        # Step 3: Customer submits clarification response with attached evidence via POST /refunds/{refund_id}/clarify
        file_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        clarify_payload = {
            "response_text": "Here is the photo of the shattered screen as requested by the supervisor.",
        }
        clarify_res = await client.post(
            f"/refunds/{refund_id}/clarify",
            data=clarify_payload,
            files={"evidence_file": ("cracked_screen.png", file_bytes, "image/png")},
        )
        assert clarify_res.status_code == 200
        clarify_data = clarify_res.json()
        assert clarify_data["status"] == "pending"
        assert clarify_data["clarification_response"] == clarify_payload["response_text"]
        assert len(clarify_data["evidence"]) == 1
        assert clarify_data["evidence"][0]["filename"] == "cracked_screen.png"
        assert clarify_data["evidence"][0]["content_type"] == "image/png"

        # Step 5: Polling until workflow resumes and reaches final status
        resumed_record = await poll_until_not_pending(client, refund_id)
        assert resumed_record["status"] in ("completed", "escalated")
        assert resumed_record["clarification_response"] == clarify_payload["response_text"]
        assert len(resumed_record["evidence"]) == 1
        assert resumed_record["evidence"][0]["filename"] == "cracked_screen.png"

    app.dependency_overrides.pop(get_evidence_storage_service, None)


@pytest.mark.asyncio
async def test_e2e_product_mismatch_pauses_and_resolves_upon_clarification(mock_repo: RefundRepository):
    """AC: Submitting a refund request with conflicting item text initially pauses in awaiting_clarification, customer response confirming the correct item resumes the graph, and refund reaches completed."""
    payload = {
        "order_id": "ORD-1008",
        "customer_request_text": "I am requesting a full refund because the mirrorless camera arrived with a shattered lens.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Submit intake request with conflicting item text
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        # Step 2: Poll status until workflow pauses at awaiting_clarification
        paused_record = await poll_until_not_pending(client, refund_id)
        assert paused_record["status"] == "awaiting_clarification"
        assert paused_record["clarification_count"] == 1
        assert paused_record["decision"] is None
        prompt = paused_record.get("clarification_prompt", "")
        assert "Smart Fitness Watch" in prompt
        assert "clarify" in prompt.lower() or "order number" in prompt.lower()

        # Step 3: Customer submits clarification confirming the correct ordered item
        clarify_payload = {
            "response_text": "I received the wrong item in my package, an incorrect Smart Fitness Watch model.",
        }
        clarify_res = await client.post(
            f"/refunds/{refund_id}/clarify", json=clarify_payload
        )
        assert clarify_res.status_code == 200

        # Step 4: Background workflow resumes, product mismatch is resolved, reaches completed
        final_record = await poll_until_not_pending(client, refund_id)
        assert final_record["status"] == "completed"
        assert final_record["decision"] == "auto_approve"
        assert final_record["clarification_count"] == 1


@pytest.mark.asyncio
async def test_e2e_product_mismatch_repeated_clarifications_exhaust_and_escalate(mock_repo: RefundRepository):
    """AC: Repeated product mismatch responses exhausting 2 clarification cycles transition to status 'escalated' and decision 'escalate'."""
    payload = {
        "order_id": "ORD-1008",
        "customer_request_text": "I am requesting a full refund because the mirrorless camera arrived with a shattered lens.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Initial intake pauses at awaiting_clarification (cycle 1)
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        clarify_1 = await poll_until_not_pending(client, refund_id)
        assert clarify_1["status"] == "awaiting_clarification"
        assert clarify_1["clarification_count"] == 1

        # Step 2: Customer provides still-conflicting clarification (cycle 2)
        res1 = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": "I received the wrong item, definitely a mirrorless camera in the box."},
        )
        assert res1.status_code == 200

        clarify_2 = await poll_until_not_pending(client, refund_id)
        assert clarify_2["status"] == "awaiting_clarification"
        assert clarify_2["clarification_count"] == 2

        # Step 3: Customer clarifies a second time with persistent mismatch (exhausts 2 attempts, routes to decision)
        res2 = await client.post(
            f"/refunds/{refund_id}/clarify",
            json={"response_text": "Still claiming the wrong item mirrorless camera, definitely a camera."},
        )
        assert res2.status_code == 200

        final_record = await poll_until_not_pending(client, refund_id)

    # Assert: escalated after max clarification cycles exhausted
    assert final_record["status"] == "escalated"
    assert final_record["decision"] == "escalate"
    assert "product mismatch" in final_record["reasoning"].lower()
    assert "not resolved" in final_record["reasoning"].lower() or "was not resolved" in final_record["reasoning"].lower()


@pytest.mark.asyncio
async def test_e2e_damaged_without_evidence_pauses_and_resumes_with_evidence(
    mock_repo: RefundRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """AC: Damaged refund claim without photos pauses at awaiting_clarification and resumes upon customer evidence upload + clarification."""
    storage_service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    app.dependency_overrides[get_evidence_storage_service] = lambda: storage_service
    monkeypatch.setattr("app.services.storage.get_evidence_storage_service", lambda: storage_service)

    expected_policy_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Multimodal model verified physical damage on the chair armrest.",
    )
    mock_policy_llm = MockToolCallingModel(
        responses=[], final_output=expected_policy_output
    )
    monkeypatch.setattr(
        "app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm
    )

    payload = {
        "order_id": "ORD-1001",
        "customer_request_text": "The chair arrived broken with a snapped armrest during transit.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Submit damaged refund request without photo evidence
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        # Step 2: Poll status until workflow pauses at awaiting_clarification
        paused_record = await poll_until_not_pending(client, refund_id)
        assert paused_record["status"] == "awaiting_clarification"
        assert paused_record["category"] == "damaged"
        assert paused_record["clarification_count"] == 1
        assert paused_record["decision"] is None
        prompt = paused_record.get("clarification_prompt", "")
        assert "photo" in prompt.lower()
        assert "packaging" in prompt.lower() or "damage" in prompt.lower()

        # Step 3: Customer uploads damage photo evidence via POST /refunds/{refund_id}/evidence
        # This automatically resumes background workflow evaluation without calling /clarify
        file_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 32
        evidence_res = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("broken_chair.jpg", file_bytes, "image/jpeg")},
        )
        assert evidence_res.status_code == 201
        evidence_data = evidence_res.json()
        assert len(evidence_data["evidence"]) == 1
        assert evidence_data["evidence"][0]["filename"] == "broken_chair.jpg"

        # Step 4: Background workflow automatically resumed, multimodal inspection passes, reaches completed
        final_record = await poll_until_not_pending(client, refund_id)
        assert final_record["status"] == "completed"
        assert final_record["decision"] == "auto_approve"
        assert final_record["category"] == "damaged"
        assert len(final_record.get("evidence", [])) == 1
        assert "broken_chair.jpg" in final_record.get("clarification_response", "")

    app.dependency_overrides.pop(get_evidence_storage_service, None)


@pytest.mark.asyncio
async def test_e2e_high_value_damaged_pauses_for_photos_and_escalates_after_evidence(
    mock_repo: RefundRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """AC: Submitting a high-value damage refund request (e.g. ORD-1003, $750) without evidence pauses in status 'awaiting_clarification' with clarification_count == 1, and subsequent clarification with image attachment transitions to status 'escalated' with evidence attached for supervisor review."""
    storage_service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    app.dependency_overrides[get_evidence_storage_service] = lambda: storage_service
    monkeypatch.setattr("app.services.storage.get_evidence_storage_service", lambda: storage_service)

    expected_policy_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses"],
        failed_rules=[],
        policy_reasoning="Multimodal model verified physical damage on monitor.",
    )
    mock_policy_llm = MockToolCallingModel(
        responses=[], final_output=expected_policy_output
    )
    monkeypatch.setattr(
        "app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm
    )

    payload = {
        "order_id": "ORD-1003",
        "customer_request_text": "The gaming monitor arrived damaged with a cracked screen.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Submit high-value damage refund request without evidence
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        # Step 2: Poll status until workflow pauses at awaiting_clarification on cycle 1
        paused_record = await poll_until_not_pending(client, refund_id)
        assert paused_record["status"] == "awaiting_clarification"
        assert paused_record["clarification_count"] == 1
        assert "photo" in paused_record.get("clarification_prompt", "").lower()

        # Step 3: Customer submits clarification with attached photo evidence
        file_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 32
        clarify_res = await client.post(
            f"/refunds/{refund_id}/clarify",
            data={"response_text": "Here is the photo of the cracked gaming monitor screen."},
            files={"evidence_file": ("cracked_monitor.jpg", file_bytes, "image/jpeg")},
        )
        assert clarify_res.status_code == 200

        # Step 4: Workflow resumes, inspects photo, and escalates due to max_order_amount ($750 > $500)
        final_record = await poll_until_not_pending(client, refund_id)
        assert final_record["status"] == "escalated"
        assert final_record["decision"] == "escalate"
        assert "supervisor" in final_record.get("reasoning", "").lower()
        assert len(final_record.get("evidence", [])) == 1
        assert final_record["evidence"][0]["filename"] == "cracked_monitor.jpg"

    app.dependency_overrides.pop(get_evidence_storage_service, None)


@pytest.mark.asyncio
async def test_e2e_high_value_damaged_evidence_upload_auto_resumes_and_escalates(
    mock_repo: RefundRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """AC: Uploading evidence directly via POST /refunds/{refund_id}/evidence on a high-value damaged request automatically resumes workflow and escalates."""
    storage_service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    app.dependency_overrides[get_evidence_storage_service] = lambda: storage_service
    monkeypatch.setattr("app.services.storage.get_evidence_storage_service", lambda: storage_service)

    expected_policy_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses"],
        failed_rules=[],
        policy_reasoning="Multimodal model verified physical damage on monitor.",
    )
    mock_policy_llm = MockToolCallingModel(
        responses=[], final_output=expected_policy_output
    )
    monkeypatch.setattr(
        "app.agents.policy_checker.get_bedrock_llm", lambda: mock_policy_llm
    )

    payload = {
        "order_id": "ORD-1003",
        "customer_request_text": "The gaming monitor arrived damaged with a cracked screen.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Submit high-value damage refund request without evidence
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        # Step 2: Poll status until workflow pauses at awaiting_clarification on cycle 1
        paused_record = await poll_until_not_pending(client, refund_id)
        assert paused_record["status"] == "awaiting_clarification"
        assert paused_record["clarification_count"] == 1

        # Step 3: Customer uploads photo evidence via POST /refunds/{refund_id}/evidence
        # Automatically resumes workflow without calling /clarify
        file_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 32
        evidence_res = await client.post(
            f"/refunds/{refund_id}/evidence",
            files={"file": ("cracked_monitor.jpg", file_bytes, "image/jpeg")},
        )
        assert evidence_res.status_code == 201

        # Step 4: Workflow automatically resumed, inspects photo, and escalates due to max_order_amount
        final_record = await poll_until_not_pending(client, refund_id)
        assert final_record["status"] == "escalated"
        assert final_record["decision"] == "escalate"
        assert "supervisor" in final_record.get("reasoning", "").lower()
        assert len(final_record.get("evidence", [])) == 1
        assert final_record["evidence"][0]["filename"] == "cracked_monitor.jpg"

    app.dependency_overrides.pop(get_evidence_storage_service, None)


@pytest.mark.asyncio
async def test_e2e_high_value_non_damaged_escalates_directly_without_clarification(
    mock_repo: RefundRepository,
):
    """AC: Submitting a high-value non-damaged refund request (e.g. changed_mind on an order exceeding $200) escalates directly to status 'escalated' on cycle 0 without pausing for clarification."""
    payload = {
        "order_id": "ORD-1010",
        "customer_request_text": "I changed my mind about this mirrorless camera and would like a refund.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        post_res = await client.post("/refunds", json=payload)
        assert post_res.status_code == 202
        refund_id = post_res.json()["refund_id"]

        final_record = await poll_until_not_pending(client, refund_id)
        assert final_record["status"] == "escalated"
        assert final_record["decision"] == "escalate"
        assert final_record.get("clarification_count", 0) == 0
        assert "supervisor" in final_record.get("reasoning", "").lower()






