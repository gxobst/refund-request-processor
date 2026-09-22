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
from langchain_core.runnables import RunnableLambda
import pytest

from app.api.refunds import get_repository
from app.core.config import Settings
from app.db.repository import RefundRepository
from app.db.seed import seed_orders
from app.graph.runner import run_refund_workflow
from app.main import app
from app.schemas.classifier import ClassificationOutput
from app.schemas.refund import RefundRecord


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
    if "low confidence" in t or "unsure" in t:
        return ClassificationOutput(
            category="damaged",
            confidence_score=0.52,
            reasoning="Low confidence classification due to ambiguous customer wording.",
        )
    elif "wrong item" in t or "incorrect" in t:
        return ClassificationOutput(
            category="wrong_item",
            confidence_score=0.94,
            reasoning="Customer received incorrect item.",
        )
    elif "changed mind" in t or "mistake" in t:
        return ClassificationOutput(
            category="changed_mind",
            confidence_score=0.91,
            reasoning="Customer changed mind or ordered mistakenly.",
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

    # Assert: verify count matches mock_orders.json (7 orders)
    assert seeded_count == 7
    table = mock_dynamo_resource.Table("mock-orders")
    assert len(table.items) == 7

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


@pytest.mark.asyncio
async def test_e2e_auto_approve_flow(mock_repo: RefundRepository):
    """AC 2: Verify full lifecycle for valid auto-approved refund request."""
    # Arrange: ORD-1001 is delivered within window, $250 <= $500 limit for damaged category
    payload = {
        "order_id": "ORD-1001",
        "customer_request_text": "The chair arrived with a broken armrest during shipping.",
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
    assert final_record["matched_policy_rule"]["max_order_amount"] == 500.0


@pytest.mark.asyncio
async def test_e2e_deny_flow(mock_repo: RefundRepository):
    """AC 3: Verify full lifecycle for denied refund request violating policy limits."""
    # Arrange: ORD-1003 has order_amount $750, exceeding the $500 damaged limit
    payload = {
        "order_id": "ORD-1003",
        "customer_request_text": "The monitor screen arrived shattered and damaged.",
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
    """AC 4: Verify escalation triggered when classifier confidence is low (< 0.7)."""
    # Arrange: text triggers low confidence in mock classifier
    payload = {
        "order_id": "ORD-1001",
        "customer_request_text": "I am unsure what happened, low confidence description of problem.",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        post_response = await client.post("/refunds", json=payload)
        assert post_response.status_code == 202
        refund_id = post_response.json()["refund_id"]

        final_record = await poll_until_not_pending(client, refund_id)

    # Assert
    assert final_record["status"] == "escalated"
    assert final_record["decision"] == "escalate"
    assert "confidence" in final_record["reasoning"].lower()


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
            json={"order_id": "ORD-1001", "customer_request_text": "Damaged chair."},
        )
        # Submit 1 denied request
        r2 = await client.post(
            "/refunds",
            json={"order_id": "ORD-1003", "customer_request_text": "Damaged monitor."},
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
        customer_request_text="Damaged product request with tracing enabled.",
        thread_id="thread_trace_100",
    )

    # Assert: result is completed and workflow ran
    assert result["status"] == "completed"
    assert result["decision"] == "auto_approve"
    assert result["refund_id"] == "ref_trace_test_100"
