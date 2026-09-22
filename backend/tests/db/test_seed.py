"""Unit tests for mock order schema and DynamoDB seeding script."""

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from app.db.seed import DEFAULT_MOCK_ORDERS_PATH, prepare_dynamo_item, seed_orders
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
        order_id="ORD-001",
        item="Noise-Cancelling Headphones",
        purchase_date="2026-09-01",
        order_amount=299.99,
        delivery_date="2026-09-03",
        delivery_status="Delivered",
    )

    # Assert
    assert order.order_id == "ORD-001"
    assert order.item == "Noise-Cancelling Headphones"
    assert order.purchase_date == date(2026, 9, 1)
    assert order.order_amount == 299.99
    assert order.delivery_date == date(2026, 9, 3)
    assert order.delivery_status == "delivered"


def test_mock_order_none_delivery_date():
    # Arrange & Act
    order = MockOrder(
        order_id="ORD-002",
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
            order_id="ORD-003",
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
            order_id="ORD-004",
            item="Item",
            purchase_date="invalid-date",
            order_amount=100.0,
            delivery_status="delivered",
        )
    assert "purchase_date" in str(exc_info.value)


# --- 2. Decimal Conversion Tests ---


def test_prepare_dynamo_item_converts_floats_to_decimal():
    # Arrange
    order = MockOrder(
        order_id="ORD-005",
        item="Office Chair",
        purchase_date="2026-09-01",
        order_amount=249.99,
        delivery_date="2026-09-03",
        delivery_status="delivered",
    )

    # Act
    item = prepare_dynamo_item(order)

    # Assert
    assert item["order_id"] == "ORD-005"
    assert isinstance(item["order_amount"], Decimal)
    assert item["order_amount"] == Decimal("249.99")
    assert item["purchase_date"] == "2026-09-01"
    assert item["delivery_date"] == "2026-09-03"
    assert item["delivery_status"] == "delivered"


def test_prepare_dynamo_item_omits_none_delivery_date():
    # Arrange
    order = MockOrder(
        order_id="ORD-006",
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
            "order_id": "CUSTOM-1",
            "item": "Mechanical Keyboard",
            "purchase_date": "2026-09-01",
            "delivery_date": "2026-09-03",
            "order_amount": 120.0,
            "delivery_status": "delivered",
        },
        {
            "order_id": "CUSTOM-2",
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
    assert "CUSTOM-1" in table.items
    assert "CUSTOM-2" in table.items


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
