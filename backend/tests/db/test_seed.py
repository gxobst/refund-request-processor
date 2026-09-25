"""Unit tests for mock order schema and DynamoDB seeding script."""

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.seed import (
    DEFAULT_MOCK_ORDERS_PATH,
    DEFAULT_ORDERS_TABLE_NAME,
    main,
    prepare_dynamo_item,
    seed_orders,
)
from app.schemas.order import MockOrder


class MockBatchWriter:
    """Mock DynamoDB batch_writer context manager."""

    def __init__(self, table: "MockDynamoTable"):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def put_item(self, Item: dict):
        self.table.items[Item["order_id"]] = Item


class MockDynamoTable:
    """Mock DynamoDB Table storing items by order_id."""

    def __init__(self, name: str = "orders"):
        self.name = name
        self.items: dict[str, dict] = {}
        self.put_item_calls: list[dict] = []

    def batch_writer(self):
        return MockBatchWriter(self)

    def put_item(self, Item: dict):
        self.put_item_calls.append(Item)
        self.items[Item["order_id"]] = Item


class MockDynamoResource:
    """Mock DynamoDB resource factory."""

    def __init__(self):
        self.tables: dict[str, MockDynamoTable] = {}

    def Table(self, name: str) -> MockDynamoTable:
        if name not in self.tables:
            self.tables[name] = MockDynamoTable(name)
        return self.tables[name]


# --- 1. Schema Validation Tests ---


def test_mock_order_valid_schema():
    # Arrange & Act
    order = MockOrder(
        order_id="ORD-1001",
        item="Noise-Cancelling Headphones",
        purchase_date="2026-09-01",
        order_amount=299.99,
        delivery_date="2026-09-03",
        delivery_status="Delivered",
    )

    # Assert
    assert order.order_id == "ORD-1001"
    assert order.item == "Noise-Cancelling Headphones"
    assert order.purchase_date == date(2026, 9, 1)
    assert order.order_amount == 299.99
    assert order.delivery_date == date(2026, 9, 3)
    assert order.delivery_status == "delivered"


def test_mock_order_none_delivery_date():
    # Arrange & Act
    order = MockOrder(
        order_id="ORD-1002",
        item="Standing Desk",
        purchase_date="2026-09-10",
        order_amount=450.0,
        delivery_date=None,
        delivery_status="in_transit",
    )

    # Assert
    assert order.delivery_date is None
    assert order.delivery_status == "in_transit"


@pytest.mark.parametrize("invalid_amount", [0.0, -10.0, -0.01])
def test_mock_order_rejects_non_positive_amount(invalid_amount: float):
    # Arrange, Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        MockOrder(
            order_id="ORD-1003",
            item="Item",
            purchase_date="2026-09-01",
            order_amount=invalid_amount,
            delivery_status="delivered",
        )
    assert "order_amount" in str(exc_info.value)


def test_mock_order_rejects_missing_required_fields():
    # Arrange, Act & Assert: missing order_id and purchase_date
    with pytest.raises(ValidationError) as exc_info:
        MockOrder(
            item="Item",
            order_amount=100.0,
            delivery_status="delivered",
        )  # type: ignore[call-arg]
    error_msg = str(exc_info.value)
    assert "order_id" in error_msg
    assert "purchase_date" in error_msg


def test_mock_order_rejects_malformed_date():
    # Arrange, Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        MockOrder(
            order_id="ORD-1004",
            item="Item",
            purchase_date="invalid-date",
            order_amount=100.0,
            delivery_status="delivered",
        )
    assert "purchase_date" in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_order_id",
    [
        "ORD-001",
        "ord-1001",
        "INV-1001",
        "ORD-10",
        "ORD-100",
        "ORD-10001",
        "ORD-ABCD",
        "ORD_1001",
        "1001",
        "",
    ],
)
def test_mock_order_rejects_invalid_order_id_pattern(invalid_order_id: str):
    """Test MockOrder rejects order_id that does not match ^ORD-\\d{4}$."""
    with pytest.raises(ValidationError) as exc_info:
        MockOrder(
            order_id=invalid_order_id,
            item="Item",
            purchase_date="2026-09-01",
            order_amount=50.0,
            delivery_status="delivered",
        )
    assert "order_id" in str(exc_info.value)


def test_mock_orders_json_order_ids_strict_pattern():
    """Verify that all mock order records in mock_orders.json strictly adhere to the ^ORD-\\d{4}$ regex format."""
    import re
    assert DEFAULT_MOCK_ORDERS_PATH.is_file(), f"Mock orders file not found: {DEFAULT_MOCK_ORDERS_PATH}"
    with open(DEFAULT_MOCK_ORDERS_PATH, "r", encoding="utf-8") as f:
        orders = json.load(f)

    assert len(orders) > 0, "mock_orders.json is empty"
    pattern = re.compile(r"^ORD-\d{4}$")
    for order in orders:
        order_id = order.get("order_id")
        assert order_id is not None, f"Order record missing order_id: {order}"
        assert pattern.match(order_id), (
            f"Mock order record ID '{order_id}' does not match required pattern '^ORD-\\d{{4}}$'"
        )


# --- 2. Decimal Conversion Tests ---


def test_prepare_dynamo_item_converts_floats_to_decimal():
    # Arrange
    order = MockOrder(
        order_id="ORD-1005",
        item="Office Chair",
        purchase_date="2026-09-01",
        order_amount=249.99,
        delivery_date="2026-09-03",
        delivery_status="delivered",
    )

    # Act
    item = prepare_dynamo_item(order)

    # Assert
    assert item["order_id"] == "ORD-1005"
    assert isinstance(item["order_amount"], Decimal)
    assert item["order_amount"] == Decimal("249.99")
    assert item["purchase_date"] == "2026-09-01"
    assert item["delivery_date"] == "2026-09-03"
    assert item["delivery_status"] == "delivered"


def test_prepare_dynamo_item_omits_none_delivery_date():
    # Arrange
    order = MockOrder(
        order_id="ORD-1006",
        item="Coffee Maker",
        purchase_date="2026-09-01",
        order_amount=79.50,
        delivery_date=None,
        delivery_status="in_transit",
    )

    # Act
    item = prepare_dynamo_item(order)

    # Assert
    assert "delivery_date" not in item
    assert isinstance(item["order_amount"], Decimal)


# --- 3. Seeding Execution Tests ---


def test_seed_orders_default_dataset():
    # Arrange
    mock_resource = MockDynamoResource()

    # Act: seed default dataset
    count = seed_orders(dynamodb_resource=mock_resource, table_name="test_orders")

    # Assert: default dataset has at least 5 orders
    assert count >= 5
    table = mock_resource.Table("test_orders")
    assert len(table.items) == count

    # Verify distinct delivery statuses and categories are present
    statuses = {item["delivery_status"] for item in table.items.values()}
    assert "delivered" in statuses
    assert "in_transit" in statuses
    assert "cancelled" in statuses

    # Verify all order amounts stored as Decimal
    for item in table.items.values():
        assert isinstance(item["order_amount"], Decimal)


def test_seed_orders_idempotent():
    # Arrange
    mock_resource = MockDynamoResource()

    # Act: run seed_orders twice on the same table
    first_count = seed_orders(dynamodb_resource=mock_resource, table_name="test_orders")
    second_count = seed_orders(dynamodb_resource=mock_resource, table_name="test_orders")

    # Assert
    assert first_count == second_count
    table = mock_resource.Table("test_orders")
    assert len(table.items) == first_count


def test_seed_orders_custom_file(tmp_path: Path):
    # Arrange: write custom valid mock orders
    custom_orders = [
        {
            "order_id": "ORD-9001",
            "item": "Mechanical Keyboard",
            "purchase_date": "2026-09-01",
            "delivery_date": "2026-09-03",
            "order_amount": 120.0,
            "delivery_status": "delivered",
        },
        {
            "order_id": "ORD-9002",
            "item": "Mouse Pad",
            "purchase_date": "2026-09-02",
            "delivery_date": None,
            "order_amount": 20.0,
            "delivery_status": "in_transit",
        },
    ]
    custom_file = tmp_path / "custom_orders.json"
    custom_file.write_text(json.dumps(custom_orders), encoding="utf-8")
    mock_resource = MockDynamoResource()

    # Act
    count = seed_orders(
        file_path=custom_file,
        table_name="custom_table",
        dynamodb_resource=mock_resource,
    )

    # Assert
    assert count == 2
    table = mock_resource.Table("custom_table")
    assert "ORD-9001" in table.items
    assert "ORD-9002" in table.items


def test_seed_orders_raises_file_not_found():
    # Arrange
    mock_resource = MockDynamoResource()

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        seed_orders(
            file_path="nonexistent_mock_orders_file.json",
            dynamodb_resource=mock_resource,
        )


def test_seed_orders_rejects_invalid_schema(tmp_path: Path):
    # Arrange: mock order with invalid negative amount
    invalid_data = [
        {
            "order_id": "INVALID-1",
            "item": "Bad Item",
            "purchase_date": "2026-09-01",
            "order_amount": -50.0,
            "delivery_status": "delivered",
        }
    ]
    invalid_file = tmp_path / "invalid_orders.json"
    invalid_file.write_text(json.dumps(invalid_data), encoding="utf-8")
    mock_resource = MockDynamoResource()

    # Act & Assert
    with pytest.raises(ValidationError):
        seed_orders(
            file_path=invalid_file,
            dynamodb_resource=mock_resource,
        )


def test_seed_orders_fallback_put_item_without_batch_writer():
    # Arrange: table without batch_writer attribute
    class TableWithoutBatchWriter:
        def __init__(self):
            self.items = {}

        def put_item(self, Item: dict):
            self.items[Item["order_id"]] = Item

    class ResourceWithoutBatchWriter:
        def __init__(self):
            self.table = TableWithoutBatchWriter()

        def Table(self, name: str):
            return self.table

    res = ResourceWithoutBatchWriter()

    # Act
    count = seed_orders(dynamodb_resource=res, table_name="test_table")

    # Assert
    assert count >= 5
    assert len(res.table.items) == count


# --- 4. Configuration, AWS Settings & CLI Entrypoint Tests (Task 16) ---


def test_default_orders_table_name_constant():
    """Verify that DEFAULT_ORDERS_TABLE_NAME is updated to 'mock-orders'."""
    assert DEFAULT_ORDERS_TABLE_NAME == "mock-orders"


def test_seed_orders_defaults_to_settings_table_name():
    """Verify seed_orders defaults to settings.dynamodb_table_orders ('mock-orders')."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        dynamodb_table_orders="mock-orders",
        aws_region="us-east-1",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        aws_session_token=None,
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.seed.get_settings", return_value=mock_settings), \
         patch("app.db.seed.boto3.resource", return_value=fake_resource) as mock_boto:
        count = seed_orders()

        assert count >= 5
        mock_boto.assert_called_once_with("dynamodb", region_name="us-east-1")
        fake_resource.Table.assert_called_once_with("mock-orders")


def test_seed_orders_with_injected_settings():
    """Verify seed_orders uses injected settings instance when provided."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    custom_settings = Settings(
        dynamodb_table_orders="custom-orders-table",
        aws_region="eu-west-1",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        aws_session_token=None,
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.seed.boto3.resource", return_value=fake_resource) as mock_boto:
        count = seed_orders(settings=custom_settings)

        assert count >= 5
        mock_boto.assert_called_once_with("dynamodb", region_name="eu-west-1")
        fake_resource.Table.assert_called_once_with("custom-orders-table")


def test_seed_orders_explicit_table_name_overrides_settings():
    """Verify explicit table_name argument overrides application settings."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        dynamodb_table_orders="default-settings-orders",
        aws_region="us-east-1",
    )

    with patch("app.db.seed.get_settings", return_value=mock_settings), \
         patch("app.db.seed.boto3.resource", return_value=fake_resource):
        count = seed_orders(table_name="explicit-orders-table")

        assert count >= 5
        fake_resource.Table.assert_called_once_with("explicit-orders-table")


def test_seed_orders_explicit_dynamodb_resource_bypasses_boto3():
    """Verify that passing an explicit dynamodb_resource bypasses boto3.resource instantiation."""
    custom_resource = MockDynamoResource()

    with patch("app.db.seed.boto3.resource") as mock_boto:
        count = seed_orders(dynamodb_resource=custom_resource)

        mock_boto.assert_not_called()
        assert count >= 5
        assert "mock-orders" in custom_resource.tables
        assert len(custom_resource.tables["mock-orders"].items) == count


def test_seed_orders_boto3_resource_with_credentials_and_endpoint():
    """Verify credentials, session token, and endpoint_url are passed to boto3.resource."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-west-2",
        aws_access_key_id="test-key-id",
        aws_secret_access_key="test-secret-key",
        aws_session_token="test-session-token",
        dynamodb_endpoint_url="http://localhost:8000",
        dynamodb_table_orders="mock-orders",
    )

    with patch("app.db.seed.get_settings", return_value=mock_settings), \
         patch("app.db.seed.boto3.resource", return_value=fake_resource) as mock_boto:
        count = seed_orders()

        assert count >= 5
        mock_boto.assert_called_once_with(
            "dynamodb",
            region_name="us-west-2",
            aws_access_key_id="test-key-id",
            aws_secret_access_key="test-secret-key",
            aws_session_token="test-session-token",
            endpoint_url="http://localhost:8000",
        )
        fake_resource.Table.assert_called_once_with("mock-orders")


def test_seed_orders_boto3_resource_with_credentials_no_session_token():
    """Verify credentials without session token pass key and secret without aws_session_token."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-west-1",
        aws_access_key_id="test-key",
        aws_secret_access_key="test-secret",
        aws_session_token=None,
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.seed.get_settings", return_value=mock_settings), \
         patch("app.db.seed.boto3.resource", return_value=fake_resource) as mock_boto:
        count = seed_orders()

        mock_boto.assert_called_once_with(
            "dynamodb",
            region_name="us-west-1",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )


def test_seed_orders_boto3_resource_without_credentials():
    """Verify boto3 standard credential chain resolution when credentials are None."""
    fake_table = MagicMock()
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    mock_settings = Settings(
        aws_region="us-east-1",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        aws_session_token=None,
        dynamodb_endpoint_url=None,
    )

    with patch("app.db.seed.get_settings", return_value=mock_settings), \
         patch("app.db.seed.boto3.resource", return_value=fake_resource) as mock_boto:
        seed_orders()

        mock_boto.assert_called_once_with(
            "dynamodb",
            region_name="us-east-1",
        )


def test_cli_main_default_arguments(capsys: pytest.CaptureFixture):
    """Verify CLI main entrypoint seeds default file path and prints result."""
    with patch("sys.argv", ["seed.py"]), \
         patch("app.db.seed.seed_orders", return_value=7) as mock_seed:
        result = main()

        assert result == 7
        mock_seed.assert_called_once_with(file_path=None)
        captured = capsys.readouterr()
        assert "Successfully seeded 7 orders into DynamoDB." in captured.out


def test_cli_main_custom_file_argument(capsys: pytest.CaptureFixture):
    """Verify CLI main entrypoint accepts a custom file path argument."""
    with patch("sys.argv", ["seed.py", "custom/orders.json"]), \
         patch("app.db.seed.seed_orders", return_value=4) as mock_seed:
        result = main()

        assert result == 4
        mock_seed.assert_called_once_with(file_path="custom/orders.json")
        captured = capsys.readouterr()
        assert "Successfully seeded 4 orders into DynamoDB." in captured.out


def test_cli_main_with_explicit_argv(capsys: pytest.CaptureFixture):
    """Verify CLI main entrypoint with explicit argv parameter."""
    with patch("app.db.seed.seed_orders", return_value=3) as mock_seed:
        result = main(["explicit/orders.json"])

        assert result == 3
        mock_seed.assert_called_once_with(file_path="explicit/orders.json")
        captured = capsys.readouterr()
        assert "Successfully seeded 3 orders into DynamoDB." in captured.out


def test_cli_module_execution(capsys: pytest.CaptureFixture):
    """Verify executing module as __main__ invokes main and prints status."""
    import runpy
    import warnings

    with patch("sys.argv", ["seed.py"]), \
         patch("app.db.seed.seed_orders", return_value=7), \
         warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("app.db.seed", run_name="__main__")
        captured = capsys.readouterr()
        assert "Successfully seeded 10 orders into DynamoDB." in captured.out


def test_numerical_parity_between_seeded_orders_and_payment_registry():
    """Verify numerical parity between seeded DynamoDB orders and MOCK_PAYMENT_REGISTRY across ORD-1001 through ORD-1010."""
    mock_dynamo = MockDynamoResource()
    with patch("app.db.seed.boto3.resource", return_value=mock_dynamo):
        count = seed_orders()
    assert count == 10
    table = mock_dynamo.tables[DEFAULT_ORDERS_TABLE_NAME]

    from app.tools.payment import MOCK_PAYMENT_REGISTRY

    overlapping_orders = [f"ORD-100{i}" for i in range(1, 10)] + ["ORD-1010"]
    for order_id in overlapping_orders:
        assert order_id in table.items
        assert order_id in MOCK_PAYMENT_REGISTRY
        seeded_amount = float(table.items[order_id]["order_amount"])
        payment_amount = float(MOCK_PAYMENT_REGISTRY[order_id]["charge_amount"])
        assert seeded_amount == payment_amount


