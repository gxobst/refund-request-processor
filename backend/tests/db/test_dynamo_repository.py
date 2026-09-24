"""Unit tests for DynamoDB refund repository."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import Settings
from app.db.repository import RefundNotFoundError, RefundRepository
from app.schemas.refund import EvidenceItem, RefundRecord


class MockDynamoTable:
    """Mock DynamoDB table for testing repository operations offline."""

    def __init__(self, name: str = "refund_requests"):
        self.name = name
        self.items: dict[str, dict] = {}

    def put_item(self, Item: dict) -> dict:
        self.items[Item["refund_id"]] = Item
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_item(self, Key: dict) -> dict:
        item = self.items.get(Key.get("refund_id"))
        if item is not None:
            return {"Item": item}
        return {}

    def scan(self, **kwargs) -> dict:
        return {"Items": list(self.items.values())}


class MockDynamoResource:
    """Mock boto3 DynamoDB resource."""

    def __init__(self):
        self.tables: dict[str, MockDynamoTable] = {}

    def Table(self, name: str) -> MockDynamoTable:
        if name not in self.tables:
            self.tables[name] = MockDynamoTable(name)
        return self.tables[name]


@pytest.fixture
def mock_resource() -> MockDynamoResource:
    return MockDynamoResource()


@pytest.fixture
def repository(mock_resource: MockDynamoResource) -> RefundRepository:
    return RefundRepository(dynamodb_resource=mock_resource, table_name="test_refunds")


def test_create_refund_request(repository: RefundRepository):
    # Arrange & Act
    record = repository.create_refund_request(
        order_id="ORD-1001",
        customer_request_text="Item arrived with a broken zipper.",
    )

    # Assert
    assert isinstance(record, RefundRecord)
    assert record.refund_id.startswith("ref_")
    assert record.order_id == "ORD-1001"
    assert record.customer_request_text == "Item arrived with a broken zipper."
    assert record.status == "pending"
    assert record.decision is None
    assert record.created_at is not None
    assert record.updated_at is not None

    # Verify directly in mocked table
    raw_item = repository.table.items.get(record.refund_id)
    assert raw_item is not None
    assert raw_item["status"] == "pending"


def test_get_refund_request_found(repository: RefundRepository):
    # Arrange
    created = repository.create_refund_request(
        order_id="ORD-1002",
        customer_request_text="Wrong color received.",
    )

    # Act
    fetched = repository.get_refund_request(created.refund_id)

    # Assert
    assert fetched is not None
    assert fetched.refund_id == created.refund_id
    assert fetched.order_id == "ORD-1002"
    assert fetched.customer_request_text == "Wrong color received."


def test_get_refund_request_not_found(repository: RefundRepository):
    # Arrange & Act
    result = repository.get_refund_request("nonexistent-refund-id")

    # Assert
    assert result is None


def test_list_refund_requests_unfiltered_and_limit(repository: RefundRepository):
    # Arrange: create 5 refund requests
    for i in range(5):
        repository.create_refund_request(
            order_id=f"ORD-LIST-{i}",
            customer_request_text=f"Request number {i}",
        )

    # Act: list all requests with limit=3
    results = repository.list_refund_requests(limit=3)

    # Assert
    assert len(results) == 3
    assert all(isinstance(r, RefundRecord) for r in results)


def test_list_refund_requests_filtered_by_status(repository: RefundRepository):
    # Arrange: create pending, completed, escalated records
    req1 = repository.create_refund_request(order_id="ORD-P", customer_request_text="Pending request")
    req2 = repository.create_refund_request(order_id="ORD-C", customer_request_text="Completed request")
    req3 = repository.create_refund_request(order_id="ORD-E", customer_request_text="Escalated request")

    # Update states
    repository.update_decision(
        refund_id=req2.refund_id,
        decision="auto_approve",
        reasoning="Within policy window",
        matched_policy_rule={"max_order_amount": 500},
        confidence_score=0.95,
        status="completed",
    )
    repository.update_decision(
        refund_id=req3.refund_id,
        decision="escalate",
        reasoning="Low classification confidence",
        matched_policy_rule=None,
        confidence_score=0.55,
        status="escalated",
    )

    # Act & Assert
    pending_list = repository.list_refund_requests(status="pending")
    completed_list = repository.list_refund_requests(status="completed")
    escalated_list = repository.list_refund_requests(status="escalated")

    assert any(r.refund_id == req1.refund_id for r in pending_list)
    assert not any(r.refund_id == req2.refund_id for r in pending_list)

    assert any(r.refund_id == req2.refund_id for r in completed_list)
    assert not any(r.refund_id == req1.refund_id for r in completed_list)

    assert any(r.refund_id == req3.refund_id for r in escalated_list)


def test_update_decision_success(repository: RefundRepository):
    # Arrange
    record = repository.create_refund_request(
        order_id="ORD-DEC-1",
        customer_request_text="Sleeve was torn on arrival.",
    )
    policy_rule = {
        "refund_window_days": 30,
        "eligible_delivery_statuses": ["delivered"],
        "max_order_amount": 500.0,
    }

    # Act
    updated = repository.update_decision(
        refund_id=record.refund_id,
        decision="auto_approve",
        reasoning="Damaged item within 30-day window and under $500 limit.",
        matched_policy_rule=policy_rule,
        confidence_score=0.98,
        status="completed",
    )

    # Assert
    assert updated.refund_id == record.refund_id
    assert updated.decision == "auto_approve"
    assert updated.status == "completed"
    assert updated.confidence_score == 0.98
    assert isinstance(updated.confidence_score, float)
    assert updated.matched_policy_rule == policy_rule

    # Verify Decimal storage in raw DynamoDB item
    raw = repository.table.items[record.refund_id]
    assert isinstance(raw["confidence_score"], Decimal)
    assert raw["confidence_score"] == Decimal("0.98")
    assert isinstance(raw["matched_policy_rule"]["max_order_amount"], Decimal)


def test_update_decision_nonexistent_id_raises_error(repository: RefundRepository):
    # Arrange, Act & Assert
    with pytest.raises((RefundNotFoundError, KeyError)):
        repository.update_decision(
            refund_id="nonexistent-id",
            decision="deny",
            reasoning="Not eligible",
            matched_policy_rule=None,
            confidence_score=0.9,
            status="completed",
        )


def test_apply_override_success(repository: RefundRepository):
    # Arrange: create and escalate a refund request
    record = repository.create_refund_request(
        order_id="ORD-OVR-1",
        customer_request_text="Ambiguous request needing human review.",
    )
    repository.update_decision(
        refund_id=record.refund_id,
        decision="escalate",
        reasoning="Borderline delivery window",
        matched_policy_rule=None,
        confidence_score=0.6,
        status="escalated",
    )

    # Act: human operator overrides to approve
    overridden = repository.apply_override(
        refund_id=record.refund_id,
        override_decision="approve",
        override_reason="Customer is VIP tier, one-time exception granted.",
    )

    # Assert
    assert overridden.refund_id == record.refund_id
    assert overridden.decision == "approve"
    assert overridden.override_decision == "approve"
    assert overridden.override_reason == "Customer is VIP tier, one-time exception granted."
    assert overridden.overridden_at is not None
    assert overridden.status == "completed"

    # Verify raw DynamoDB state
    raw = repository.table.items[record.refund_id]
    assert raw["decision"] == "approve"
    assert raw["override_decision"] == "approve"
    assert raw["status"] == "completed"


def test_apply_override_nonexistent_id_raises_error(repository: RefundRepository):
    # Arrange, Act & Assert
    with pytest.raises((RefundNotFoundError, KeyError)):
        repository.apply_override(
            refund_id="nonexistent-id",
            override_decision="deny",
            override_reason="Invalid request",
        )


# --- Tests for RefundRepository configuration & AWS initialization (Task 14) ---


def test_init_default_settings():
    """Verify default initialization uses application settings and defaults."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-east-1",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        aws_session_token=None,
        dynamodb_table_refunds="refund-requests",
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.repository.get_settings", return_value=mock_settings), \
         patch("app.db.repository.boto3.resource", return_value=fake_resource) as mock_boto:
        repo = RefundRepository()

        assert repo.table_name == "refund-requests"
        mock_boto.assert_called_once_with("dynamodb", region_name="us-east-1")
        fake_resource.Table.assert_called_once_with("refund-requests")
        assert repo.table == fake_table


def test_init_explicit_table_name_overrides_settings():
    """Verify that an explicit table_name overrides the default from settings."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-east-1",
        dynamodb_table_refunds="default-settings-table",
    )

    with patch("app.db.repository.get_settings", return_value=mock_settings), \
         patch("app.db.repository.boto3.resource", return_value=fake_resource):
        repo = RefundRepository(table_name="custom-override-table")

        assert repo.table_name == "custom-override-table"
        fake_resource.Table.assert_called_once_with("custom-override-table")


def test_init_explicit_dynamodb_resource_bypasses_boto3_resource():
    """Verify that passing an explicit dynamodb_resource does not invoke boto3.resource."""
    custom_resource = MockDynamoResource()

    with patch("app.db.repository.boto3.resource") as mock_boto:
        repo = RefundRepository(dynamodb_resource=custom_resource)

        mock_boto.assert_not_called()
        assert repo.dynamodb_resource is custom_resource
        assert repo.table_name == "refund-requests"
        assert repo.table.name == "refund-requests"


def test_init_explicit_resource_and_table_name_bypasses_get_settings():
    """Verify that passing both explicit resource and table_name avoids calling get_settings."""
    custom_resource = MockDynamoResource()

    with patch("app.db.repository.get_settings") as mock_get_settings, \
         patch("app.db.repository.boto3.resource") as mock_boto:
        repo = RefundRepository(
            dynamodb_resource=custom_resource,
            table_name="explicit-table",
        )

        mock_boto.assert_not_called()
        mock_get_settings.assert_not_called()
        assert repo.dynamodb_resource is custom_resource
        assert repo.table_name == "explicit-table"
        assert repo.table.name == "explicit-table"


def test_init_with_explicit_credentials_and_endpoint_url():
    """Verify explicit AWS credentials, session token, and endpoint_url are passed to boto3.resource."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="eu-west-1",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        aws_session_token="test-session-token",
        dynamodb_endpoint_url="http://localhost:8000",
        dynamodb_table_refunds="local-refunds",
    )

    with patch("app.db.repository.get_settings", return_value=mock_settings), \
         patch("app.db.repository.boto3.resource", return_value=fake_resource) as mock_boto:
        repo = RefundRepository()

        assert repo.table_name == "local-refunds"
        mock_boto.assert_called_once_with(
            "dynamodb",
            region_name="eu-west-1",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            aws_session_token="test-session-token",
            endpoint_url="http://localhost:8000",
        )


def test_init_with_credentials_without_session_token():
    """Verify credentials without session token pass key and secret without aws_session_token."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="ap-southeast-1",
        aws_access_key_id="test-key",
        aws_secret_access_key="test-secret",
        aws_session_token=None,
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.repository.get_settings", return_value=mock_settings), \
         patch("app.db.repository.boto3.resource", return_value=fake_resource) as mock_boto:
        repo = RefundRepository()

        mock_boto.assert_called_once_with(
            "dynamodb",
            region_name="ap-southeast-1",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )
        kwargs = mock_boto.call_args[1]
        assert "aws_session_token" not in kwargs
        assert "endpoint_url" not in kwargs


def test_init_missing_credentials_allows_boto3_credential_chain():
    """Verify that when credentials are None, boto3.resource is called without credential kwargs."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-west-2",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        aws_session_token=None,
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.repository.get_settings", return_value=mock_settings), \
         patch("app.db.repository.boto3.resource", return_value=fake_resource) as mock_boto:
        repo = RefundRepository()

        mock_boto.assert_called_once_with("dynamodb", region_name="us-west-2")
        kwargs = mock_boto.call_args[1]
        assert "aws_access_key_id" not in kwargs
        assert "aws_secret_access_key" not in kwargs
        assert "aws_session_token" not in kwargs


def test_init_partial_credentials_omits_credential_kwargs():
    """Verify that if access key is present but secret key is None/empty, credential kwargs are omitted."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-east-1",
        aws_access_key_id="only-access-key",
        aws_secret_access_key=None,
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.repository.get_settings", return_value=mock_settings), \
         patch("app.db.repository.boto3.resource", return_value=fake_resource) as mock_boto:
        repo = RefundRepository()

        mock_boto.assert_called_once_with("dynamodb", region_name="us-east-1")
        kwargs = mock_boto.call_args[1]
        assert "aws_access_key_id" not in kwargs
        assert "aws_secret_access_key" not in kwargs


def test_init_endpoint_url_without_credentials():
    """Verify endpoint_url is passed even when credentials are not configured."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-east-1",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        dynamodb_endpoint_url="http://localhost:4566",
    )

    with patch("app.db.repository.get_settings", return_value=mock_settings), \
         patch("app.db.repository.boto3.resource", return_value=fake_resource) as mock_boto:
        repo = RefundRepository()

        mock_boto.assert_called_once_with(
            "dynamodb",
            region_name="us-east-1",
            endpoint_url="http://localhost:4566",
        )
        kwargs = mock_boto.call_args[1]
        assert "aws_access_key_id" not in kwargs
        assert "aws_secret_access_key" not in kwargs


# --- Tests for clarification requests and customer responses (Task 22) ---


def test_create_refund_request_default_clarification_values(repository: RefundRepository):
    """Verify newly created refund request has default clarification fields."""
    record = repository.create_refund_request(
        order_id="ORD-CLAR-01",
        customer_request_text="Clarification test order",
    )
    assert record.clarification_prompt is None
    assert record.clarification_response is None
    assert record.clarification_count == 0

    raw = repository.table.items[record.refund_id]
    assert raw.get("clarification_prompt") is None
    assert raw.get("clarification_response") is None
    assert raw.get("clarification_count") == 0


def test_deserialization_legacy_record_without_clarification(repository: RefundRepository):
    """Verify legacy DynamoDB items lacking clarification attributes deserialize cleanly."""
    legacy_item = {
        "refund_id": "ref_legacy_01",
        "order_id": "ORD-LEGACY",
        "customer_request_text": "Legacy refund without clarification fields",
        "status": "pending",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    # Direct model validation
    record = RefundRecord.model_validate(legacy_item)
    assert record.clarification_prompt is None
    assert record.clarification_response is None
    assert record.clarification_count == 0

    # Retrieval through repository
    repository.table.items["ref_legacy_01"] = legacy_item
    fetched = repository.get_refund_request("ref_legacy_01")
    assert fetched is not None
    assert fetched.clarification_prompt is None
    assert fetched.clarification_response is None
    assert fetched.clarification_count == 0


def test_request_clarification_success(repository: RefundRepository):
    """Verify request_clarification sets status, prompt, increments count, and persists."""
    record = repository.create_refund_request(
        order_id="ORD-CLAR-02",
        customer_request_text="Need refund for damaged jacket",
    )
    initial_updated_at = record.updated_at

    updated = repository.request_clarification(
        refund_id=record.refund_id,
        clarification_prompt="Could you specify where the damage is located?",
    )

    assert updated.refund_id == record.refund_id
    assert updated.status == "awaiting_clarification"
    assert updated.clarification_prompt == "Could you specify where the damage is located?"
    assert updated.clarification_count == 1
    assert updated.clarification_response is None
    assert updated.updated_at >= initial_updated_at

    # Check raw DynamoDB storage
    raw = repository.table.items[record.refund_id]
    assert raw["status"] == "awaiting_clarification"
    assert raw["clarification_prompt"] == "Could you specify where the damage is located?"
    assert raw["clarification_count"] == 1

    # Second clarification cycle increments count
    second_updated = repository.request_clarification(
        refund_id=record.refund_id,
        clarification_prompt="Could you also provide photo evidence?",
    )
    assert second_updated.status == "awaiting_clarification"
    assert second_updated.clarification_prompt == "Could you also provide photo evidence?"
    assert second_updated.clarification_count == 2


@pytest.mark.parametrize("blank_prompt", ["", "   ", "\t\n"])
def test_request_clarification_blank_prompt_raises_value_error(
    repository: RefundRepository, blank_prompt: str
):
    """Verify request_clarification rejects blank or empty clarification prompts."""
    record = repository.create_refund_request(
        order_id="ORD-CLAR-03",
        customer_request_text="Test blank prompt",
    )
    with pytest.raises(ValueError, match="clarification_prompt cannot be blank"):
        repository.request_clarification(
            refund_id=record.refund_id,
            clarification_prompt=blank_prompt,
        )


def test_request_clarification_nonexistent_id_raises_not_found(repository: RefundRepository):
    """Verify request_clarification raises RefundNotFoundError for nonexistent ID."""
    with pytest.raises((RefundNotFoundError, KeyError)):
        repository.request_clarification(
            refund_id="nonexistent-ref-id",
            clarification_prompt="Valid question",
        )


def test_submit_clarification_response_success(repository: RefundRepository):
    """Verify submit_clarification_response updates response, resets status to pending, and persists."""
    record = repository.create_refund_request(
        order_id="ORD-CLAR-04",
        customer_request_text="Missing item from box",
    )
    repository.request_clarification(
        refund_id=record.refund_id,
        clarification_prompt="Which item from your order was missing?",
    )

    responded = repository.submit_clarification_response(
        refund_id=record.refund_id,
        clarification_response="The blue wool scarf was missing from the box.",
    )

    assert responded.refund_id == record.refund_id
    assert responded.status == "pending"
    assert responded.clarification_response == "The blue wool scarf was missing from the box."
    assert responded.clarification_prompt == "Which item from your order was missing?"
    assert responded.clarification_count == 1

    # Check raw DynamoDB storage
    raw = repository.table.items[record.refund_id]
    assert raw["status"] == "pending"
    assert raw["clarification_response"] == "The blue wool scarf was missing from the box."


@pytest.mark.parametrize("blank_response", ["", "   ", "\t\n"])
def test_submit_clarification_response_blank_response_raises_value_error(
    repository: RefundRepository, blank_response: str
):
    """Verify submit_clarification_response rejects blank or empty responses."""
    record = repository.create_refund_request(
        order_id="ORD-CLAR-05",
        customer_request_text="Item damaged",
    )
    repository.request_clarification(
        refund_id=record.refund_id,
        clarification_prompt="Please explain damage",
    )
    with pytest.raises(ValueError, match="clarification_response cannot be blank"):
        repository.submit_clarification_response(
            refund_id=record.refund_id,
            clarification_response=blank_response,
        )


def test_submit_clarification_response_nonexistent_id_raises_not_found(
    repository: RefundRepository,
):
    """Verify submit_clarification_response raises RefundNotFoundError for nonexistent ID."""
    with pytest.raises((RefundNotFoundError, KeyError)):
        repository.submit_clarification_response(
            refund_id="nonexistent-ref-id",
            clarification_response="Valid customer answer",
        )


def test_list_refund_requests_filter_awaiting_clarification(repository: RefundRepository):
    """Verify list_refund_requests correctly filters by awaiting_clarification status."""
    r1 = repository.create_refund_request(order_id="ORD-FLT-1", customer_request_text="Request 1")
    r2 = repository.create_refund_request(order_id="ORD-FLT-2", customer_request_text="Request 2")
    r3 = repository.create_refund_request(order_id="ORD-FLT-3", customer_request_text="Request 3")

    repository.request_clarification(
        refund_id=r2.refund_id,
        clarification_prompt="Please clarify request 2",
    )

    clarification_list = repository.list_refund_requests(status="awaiting_clarification")
    pending_list = repository.list_refund_requests(status="pending")

    assert len(clarification_list) == 1
    assert clarification_list[0].refund_id == r2.refund_id
    assert clarification_list[0].status == "awaiting_clarification"
    assert clarification_list[0].clarification_prompt == "Please clarify request 2"

    assert not any(r.refund_id == r2.refund_id for r in pending_list)
    assert any(r.refund_id == r1.refund_id for r in pending_list)
    assert any(r.refund_id == r3.refund_id for r in pending_list)


def test_update_decision_and_apply_override_preserve_clarification_fields(
    repository: RefundRepository,
):
    """Verify update_decision and apply_override preserve existing clarification fields."""
    record = repository.create_refund_request(
        order_id="ORD-PRES-1",
        customer_request_text="Ambiguous item issue",
    )
    repository.request_clarification(
        refund_id=record.refund_id,
        clarification_prompt="Please specify condition of the packaging.",
    )
    repository.submit_clarification_response(
        refund_id=record.refund_id,
        clarification_response="The packaging was torn open and wet.",
    )

    # Now decision update
    updated_dec = repository.update_decision(
        refund_id=record.refund_id,
        decision="escalate",
        reasoning="Packaging damaged but item condition ambiguous.",
        matched_policy_rule=None,
        confidence_score=0.6,
        status="escalated",
    )

    assert updated_dec.clarification_prompt == "Please specify condition of the packaging."
    assert updated_dec.clarification_response == "The packaging was torn open and wet."
    assert updated_dec.clarification_count == 1

    raw_dec = repository.table.items[record.refund_id]
    assert raw_dec["clarification_prompt"] == "Please specify condition of the packaging."
    assert raw_dec["clarification_response"] == "The packaging was torn open and wet."
    assert raw_dec["clarification_count"] == 1

    # Now apply override
    overridden = repository.apply_override(
        refund_id=record.refund_id,
        override_decision="approve",
        override_reason="Customer verified carrier damage.",
    )

    assert overridden.clarification_prompt == "Please specify condition of the packaging."
    assert overridden.clarification_response == "The packaging was torn open and wet."
    assert overridden.clarification_count == 1

    raw_ovr = repository.table.items[record.refund_id]
    assert raw_ovr["clarification_prompt"] == "Please specify condition of the packaging."
    assert raw_ovr["clarification_response"] == "The packaging was torn open and wet."
    assert raw_ovr["clarification_count"] == 1


def test_refund_workflow_state_clarification_fields():
    """Verify RefundWorkflowState supports clarification fields and maintains total=False."""
    from app.graph.state import RefundWorkflowState

    # State without clarification fields does not raise KeyError
    minimal_state: RefundWorkflowState = {
        "refund_id": "ref_min",
        "order_id": "ORD-MIN",
        "customer_request_text": "Minimal test",
    }
    assert minimal_state.get("clarification_prompt") is None
    assert minimal_state.get("needs_clarification") is None

    # State with clarification fields
    full_clarification_state: RefundWorkflowState = {
        "refund_id": "ref_full",
        "clarification_prompt": "Are you sure?",
        "clarification_response": "Yes, positive.",
        "clarification_count": 1,
        "needs_clarification": True,
    }
    assert full_clarification_state["clarification_prompt"] == "Are you sure?"
    assert full_clarification_state["clarification_response"] == "Yes, positive."
    assert full_clarification_state["clarification_count"] == 1
    assert full_clarification_state["needs_clarification"] is True


def test_create_refund_request_initializes_empty_tool_calls(repository: RefundRepository):
    """Verify create_refund_request initializes and returns tool_calls == []."""
    record = repository.create_refund_request(
        order_id="ORD-AUDIT-01",
        customer_request_text="Tool calls initial test",
    )
    assert record.tool_calls == []
    raw = repository.table.items[record.refund_id]
    assert raw["tool_calls"] == []


def test_update_decision_persists_and_retrieves_multiple_tool_calls(repository: RefundRepository):
    """Verify update_decision persists multiple tool_calls items with nested dictionaries."""
    record = repository.create_refund_request(
        order_id="ORD-AUDIT-02",
        customer_request_text="Testing multiple tool calls persistence",
    )

    sample_tool_calls = [
        {
            "tool_name": "query_carrier_tracking",
            "tool_call_id": "call_track_1",
            "tool_input": {"tracking_number": "1Z9999999999999999"},
            "tool_output": {
                "found": True,
                "tracking_number": "1Z9999999999999999",
                "carrier": "FedEx",
                "delivery_status": "delivered",
                "delivery_date": "2026-09-15",
                "delivery_address": "123 Main St",
                "proof_of_delivery_photo_available": True,
                "events": [{"timestamp": "2026-09-15T10:00:00Z", "status": "Delivered"}],
                "error": None,
            },
            "timestamp": "2026-09-23T18:00:00+00:00",
        },
        {
            "tool_name": "query_payment_transaction",
            "tool_call_id": "call_pay_2",
            "tool_input": {"order_id": "ORD-AUDIT-02"},
            "tool_output": {
                "found": True,
                "order_id": "ORD-AUDIT-02",
                "transaction_id": "ch_3Pz7Q02eZvKYlo2C01234567",
                "charge_status": "succeeded",
                "payment_method": "card_visa",
                "charge_amount": 149.99,
                "currency": "usd",
                "dispute_status": "none",
                "refund_eligibility": True,
                "error": None,
            },
            "timestamp": "2026-09-23T18:01:00+00:00",
        },
    ]

    updated = repository.update_decision(
        refund_id=record.refund_id,
        decision="auto_approve",
        reasoning="All checks passed.",
        matched_policy_rule={"rule": "late_delivery"},
        confidence_score=0.95,
        status="completed",
        tool_calls=sample_tool_calls,
    )

    assert updated.tool_calls == sample_tool_calls

    # Retrieve from DB via get_refund_request
    fetched = repository.get_refund_request(record.refund_id)
    assert fetched is not None
    assert fetched.tool_calls == sample_tool_calls
    assert len(fetched.tool_calls) == 2
    assert fetched.tool_calls[0]["tool_name"] == "query_carrier_tracking"
    assert fetched.tool_calls[1]["tool_name"] == "query_payment_transaction"
    assert fetched.tool_calls[1]["tool_output"]["charge_amount"] == 149.99
    assert isinstance(fetched.tool_calls[1]["tool_output"]["charge_amount"], float)


def test_update_decision_none_tool_calls_preserves_existing(repository: RefundRepository):
    """Verify update_decision with tool_calls=None preserves existing tool_calls."""
    record = repository.create_refund_request(
        order_id="ORD-AUDIT-03",
        customer_request_text="Testing tool calls preservation",
    )
    initial_calls = [
        {
            "tool_name": "query_carrier_tracking",
            "tool_call_id": "call_preserve_1",
            "tool_input": {"tracking_number": "TRK-001"},
            "tool_output": {"found": True, "delivery_status": "delivered"},
            "timestamp": "2026-09-23T18:00:00+00:00",
        }
    ]
    # First update with tool_calls
    repository.update_decision(
        refund_id=record.refund_id,
        decision="escalate",
        reasoning="Initial check",
        matched_policy_rule=None,
        confidence_score=0.5,
        status="escalated",
        tool_calls=initial_calls,
    )

    # Second update without tool_calls parameter (tool_calls=None)
    updated_again = repository.update_decision(
        refund_id=record.refund_id,
        decision="deny",
        reasoning="Denied after review",
        matched_policy_rule=None,
        confidence_score=0.9,
        status="completed",
        tool_calls=None,
    )

    assert updated_again.tool_calls == initial_calls
    fetched = repository.get_refund_request(record.refund_id)
    assert fetched is not None
    assert fetched.tool_calls == initial_calls


def test_persisting_tool_calls_with_floats_converts_cleanly(repository: RefundRepository):
    """Verify persisting tool_calls containing float numbers succeeds without FloatTypeError and reloads as float."""
    record = repository.create_refund_request(
        order_id="ORD-AUDIT-04",
        customer_request_text="Testing float conversion",
    )
    float_tool_calls = [
        {
            "tool_name": "query_payment_transaction",
            "tool_call_id": "call_float_1",
            "tool_input": {"order_id": "ORD-AUDIT-04"},
            "tool_output": {
                "charge_amount": 149.99,
                "fee": 4.65,
                "nested": {"refund_ratio": 0.85},
            },
            "timestamp": "2026-09-23T18:00:00+00:00",
        }
    ]

    repository.update_decision(
        refund_id=record.refund_id,
        decision="auto_approve",
        reasoning="Float test passed.",
        matched_policy_rule=None,
        confidence_score=0.92,
        status="completed",
        tool_calls=float_tool_calls,
    )

    # Check raw DynamoDB item has Decimal values
    raw = repository.table.items[record.refund_id]
    raw_calls = raw["tool_calls"]
    assert isinstance(raw_calls[0]["tool_output"]["charge_amount"], Decimal)
    assert raw_calls[0]["tool_output"]["charge_amount"] == Decimal("149.99")
    assert isinstance(raw_calls[0]["tool_output"]["nested"]["refund_ratio"], Decimal)

    # Check retrieved object has standard float values
    fetched = repository.get_refund_request(record.refund_id)
    assert fetched is not None
    assert isinstance(fetched.tool_calls[0]["tool_output"]["charge_amount"], float)
    assert fetched.tool_calls[0]["tool_output"]["charge_amount"] == 149.99
    assert isinstance(fetched.tool_calls[0]["tool_output"]["nested"]["refund_ratio"], float)
    assert fetched.tool_calls[0]["tool_output"]["nested"]["refund_ratio"] == 0.85


def test_refund_record_deserializes_missing_tool_calls_to_empty_list(repository: RefundRepository):
    """Verify deserialization of legacy DynamoDB items lacking tool_calls attribute defaults to []."""
    legacy_item = {
        "refund_id": "ref_legacy_audit",
        "order_id": "ORD-LEGACY",
        "customer_request_text": "Legacy record without tool_calls",
        "status": "pending",
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }
    repository.table.items["ref_legacy_audit"] = legacy_item
    fetched = repository.get_refund_request("ref_legacy_audit")
    assert fetched is not None
    assert fetched.tool_calls == []


def test_update_decision_persists_and_retrieves_approval_email_text(repository: RefundRepository):
    """Verify update_decision persists approval_email_text for auto_approve and retrieves cleanly."""
    record = repository.create_refund_request(
        order_id="ORD-1001",
        customer_request_text="Need refund for chair",
    )
    email_text = "Dear Customer,\nYour refund for order ORD-1001 is approved.\nRMA-1001-AUTH\nSincerely,\nSupport"

    updated = repository.update_decision(
        refund_id=record.refund_id,
        decision="auto_approve",
        reasoning="Policy met.",
        matched_policy_rule={"rule": "damaged"},
        confidence_score=0.95,
        status="completed",
        approval_email_text=email_text,
    )
    assert updated.approval_email_text == email_text

    fetched = repository.get_refund_request(record.refund_id)
    assert fetched is not None
    assert fetched.approval_email_text == email_text

    # Updating to deny clears or sets approval_email_text to None
    denied = repository.update_decision(
        refund_id=record.refund_id,
        decision="deny",
        reasoning="Ineligible.",
        matched_policy_rule=None,
        confidence_score=0.99,
        status="completed",
    )
    assert denied.approval_email_text is None
    fetched_denied = repository.get_refund_request(record.refund_id)
    assert fetched_denied is not None
    assert fetched_denied.approval_email_text is None


def test_apply_override_persists_and_retrieves_approval_email_text(repository: RefundRepository):
    """Verify apply_override generates and persists approval_email_text on approve, and None on deny."""
    # 1. Approve override
    rec_approve = repository.create_refund_request(
        order_id="ORD-1002",
        customer_request_text="Damaged headphones",
    )
    overridden_approve = repository.apply_override(
        refund_id=rec_approve.refund_id,
        override_decision="approve",
        override_reason="Supervisor approved replacement/refund.",
    )
    assert overridden_approve.decision == "approve"
    assert overridden_approve.approval_email_text is not None
    assert "Dear Customer," in overridden_approve.approval_email_text
    assert "ORD-1002" in overridden_approve.approval_email_text
    assert "RMA" in overridden_approve.approval_email_text

    fetched_approve = repository.get_refund_request(rec_approve.refund_id)
    assert fetched_approve is not None
    assert fetched_approve.approval_email_text == overridden_approve.approval_email_text

    # 2. Deny override
    rec_deny = repository.create_refund_request(
        order_id="ORD-1003",
        customer_request_text="Monitor issue",
    )
    overridden_deny = repository.apply_override(
        refund_id=rec_deny.refund_id,
        override_decision="deny",
        override_reason="User damage confirmed.",
    )
    assert overridden_deny.decision == "deny"
    assert overridden_deny.approval_email_text is None

    fetched_deny = repository.get_refund_request(rec_deny.refund_id)
    assert fetched_deny is not None
    assert fetched_deny.approval_email_text is None


def test_refund_record_deserializes_missing_approval_email_text_to_none(repository: RefundRepository):
    """Verify that legacy DynamoDB items lacking approval_email_text attribute deserialize cleanly with None."""
    legacy_item = {
        "refund_id": "ref_legacy_no_email",
        "order_id": "ORD-LEGACY-001",
        "customer_request_text": "Legacy record without approval_email_text",
        "status": "completed",
        "decision": "auto_approve",
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }
    repository.table.items["ref_legacy_no_email"] = legacy_item
    fetched = repository.get_refund_request("ref_legacy_no_email")
    assert fetched is not None
    assert fetched.approval_email_text is None


def test_add_evidence_persists_and_retrieves_single_and_multiple_items(repository: RefundRepository):
    """Verify add_evidence persists single and multiple evidence items with both model and dict inputs."""
    record = repository.create_refund_request(
        order_id="ORD-EVI-001",
        customer_request_text="Crushed box with shattered glass",
    )
    assert record.evidence == []

    # 1. Add first item via EvidenceItem instance
    item1 = EvidenceItem(
        storage_key="evidence/ORD-EVI-001/uuid1_box.jpg",
        filename="box.jpg",
        content_type="image/jpeg",
        size_bytes=102400,
        url="https://bucket.s3.amazonaws.com/evidence/ORD-EVI-001/uuid1_box.jpg",
    )
    updated1 = repository.add_evidence(refund_id=record.refund_id, evidence_item=item1)
    assert len(updated1.evidence) == 1
    assert updated1.evidence[0].filename == "box.jpg"
    assert updated1.evidence[0].storage_key == item1.storage_key
    assert updated1.evidence[0].size_bytes == 102400

    fetched1 = repository.get_refund_request(record.refund_id)
    assert fetched1 is not None
    assert len(fetched1.evidence) == 1
    assert fetched1.evidence[0].filename == "box.jpg"

    # 2. Add second item via dict
    dict_item = {
        "storage_key": "evidence/ORD-EVI-001/uuid2_glass.png",
        "filename": "glass.png",
        "content_type": "image/png",
        "size_bytes": 204800,
        "url": "/static/uploads/evidence/ORD-EVI-001/uuid2_glass.png",
    }
    updated2 = repository.add_evidence(refund_id=record.refund_id, evidence_item=dict_item)
    assert len(updated2.evidence) == 2
    assert updated2.evidence[0].filename == "box.jpg"
    assert updated2.evidence[1].filename == "glass.png"
    assert updated2.evidence[1].content_type == "image/png"
    assert updated2.evidence[1].size_bytes == 204800

    fetched2 = repository.get_refund_request(record.refund_id)
    assert fetched2 is not None
    assert len(fetched2.evidence) == 2
    assert fetched2.evidence[0].filename == "box.jpg"
    assert fetched2.evidence[1].filename == "glass.png"


def test_add_evidence_not_found_raises_refund_not_found_error(repository: RefundRepository):
    """Verify add_evidence raises RefundNotFoundError when refund_id does not exist."""
    item = EvidenceItem(
        storage_key="evidence/UNKNOWN/test.jpg",
        filename="test.jpg",
        content_type="image/jpeg",
        size_bytes=100,
        url="/static/uploads/evidence/UNKNOWN/test.jpg",
    )
    with pytest.raises(RefundNotFoundError, match="Refund request with id 'nonexistent' not found"):
        repository.add_evidence(refund_id="nonexistent", evidence_item=item)


def test_refund_record_deserializes_missing_evidence_to_empty_list(repository: RefundRepository):
    """Verify that legacy DynamoDB items lacking an evidence attribute deserialize cleanly with evidence=[]."""
    legacy_item = {
        "refund_id": "ref_legacy_no_evidence",
        "order_id": "ORD-LEGACY-002",
        "customer_request_text": "Legacy record before evidence feature",
        "status": "pending",
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }
    repository.table.items["ref_legacy_no_evidence"] = legacy_item
    fetched = repository.get_refund_request("ref_legacy_no_evidence")
    assert fetched is not None
    assert fetched.evidence == []




