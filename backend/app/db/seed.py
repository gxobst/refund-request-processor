"""DynamoDB seeding script for mock order data."""

from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any
import boto3

from app.core.config import Settings, get_settings
from app.schemas.order import MockOrder

DEFAULT_MOCK_ORDERS_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_orders.json"
DEFAULT_ORDERS_TABLE_NAME = "mock-orders"


def prepare_dynamo_item(order: MockOrder) -> dict[str, Any]:
    """Prepare a MockOrder instance for DynamoDB storage with Decimal types."""
    item: dict[str, Any] = {
        "order_id": order.order_id,
        "item": order.item,
        "purchase_date": order.purchase_date.isoformat(),
        "order_amount": Decimal(str(order.order_amount)),
        "delivery_status": order.delivery_status,
    }
    if order.delivery_date is not None:
        item["delivery_date"] = order.delivery_date.isoformat()
    return item


def seed_orders(
    file_path: Path | str | None = None,
    table_name: str | None = None,
    dynamodb_resource: Any = None,
    settings: Settings | None = None,
) -> int:
    """Load mock orders from disk, validate against schema, and seed into DynamoDB.

    Args:
        file_path: Path to the mock orders JSON file. Defaults to app/data/mock_orders.json.
        table_name: DynamoDB table name. Defaults to settings.dynamodb_table_orders ('mock-orders').
        dynamodb_resource: boto3 DynamoDB resource. If None, initialized using settings.
        settings: Application Settings instance. Defaults to get_settings().

    Returns:
        Number of seeded orders.

    Raises:
        FileNotFoundError: If the mock orders file is not found.
        pydantic.ValidationError: If any order record fails schema validation.
    """
    if settings is None:
        settings = get_settings()

    path = Path(file_path) if file_path is not None else DEFAULT_MOCK_ORDERS_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Mock orders file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    if not isinstance(raw_items, list):
        raise ValueError("Mock orders JSON must contain a list of orders.")

    # Validate each item using MockOrder schema
    validated_orders = [MockOrder.model_validate(item) for item in raw_items]

    # Convert to DynamoDB format (Decimals for numbers, ISO strings for dates)
    prepared_items = [prepare_dynamo_item(order) for order in validated_orders]

    target_table_name = table_name if table_name is not None else settings.dynamodb_table_orders

    if dynamodb_resource is None:
        kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
        }
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            if settings.aws_session_token:
                kwargs["aws_session_token"] = settings.aws_session_token
        if settings.dynamodb_endpoint_url:
            kwargs["endpoint_url"] = settings.dynamodb_endpoint_url

        dynamodb_resource = boto3.resource("dynamodb", **kwargs)

    table = dynamodb_resource.Table(target_table_name)

    # Use batch_writer if supported, fallback to individual put_item
    try:
        with table.batch_writer() as batch:
            for item in prepared_items:
                batch.put_item(Item=item)
    except (AttributeError, TypeError):
        for item in prepared_items:
            table.put_item(Item=item)

    return len(prepared_items)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for seeding mock orders into DynamoDB."""
    args = sys.argv[1:] if argv is None else argv
    orders_path = args[0] if len(args) > 0 else None
    seeded_count = seed_orders(file_path=orders_path)
    print(f"Successfully seeded {seeded_count} orders into DynamoDB.")
    return seeded_count


if __name__ == "__main__":
    main()
