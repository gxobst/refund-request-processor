"""Unit tests for DynamoDB refund repository."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import Settings
from app.db.repository import RefundNotFoundError, RefundRepository
from app.schemas.refund import RefundRecord


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

