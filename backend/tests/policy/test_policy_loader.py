"""Unit tests for refund policy schema and static policy loader."""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from app.policy.loader import load_policies
from app.policy.schema import CategoryPolicy, PolicyConfig, RefundCategory


def test_load_policies_default_succeeds():
    # Arrange: use default path

    # Act: load default policies
    config = load_policies()

    # Assert: verify all 5 categories are loaded with expected schemas
    assert isinstance(config, PolicyConfig)
    assert isinstance(config.damaged, CategoryPolicy)
    assert isinstance(config.wrong_item, CategoryPolicy)
    assert isinstance(config.changed_mind, CategoryPolicy)
    assert isinstance(config.late_delivery, CategoryPolicy)
    assert isinstance(config.missing_item, CategoryPolicy)

    # Verify specific seeded rules
    assert config.damaged.refund_window_days == 30
    assert config.damaged.eligible_delivery_statuses == ["delivered"]
    assert config.damaged.max_order_amount == 500.0

    assert config.wrong_item.refund_window_days == 30
    assert config.wrong_item.eligible_delivery_statuses == ["delivered"]
    assert config.wrong_item.max_order_amount == 1000.0

    assert config.changed_mind.refund_window_days == 14
    assert config.changed_mind.eligible_delivery_statuses == ["delivered"]
    assert config.changed_mind.max_order_amount == 200.0

    assert config.late_delivery.refund_window_days == 14
    assert config.late_delivery.eligible_delivery_statuses == ["in_transit", "delivered"]
    assert config.late_delivery.max_order_amount == 300.0

    assert config.missing_item.refund_window_days == 30
    assert config.missing_item.eligible_delivery_statuses == ["delivered"]
    assert config.missing_item.max_order_amount == 1000.0


def test_policy_config_indexing_and_get():
    # Arrange
    config = load_policies()

    # Act & Assert
    assert config["damaged"] == config.damaged
    assert config[RefundCategory.DAMAGED] == config.damaged
    assert config.get("wrong_item") == config.wrong_item
    assert config.get("unknown_category", None) is None

    with pytest.raises(KeyError):
        _ = config["nonexistent_category"]


def test_load_policies_custom_valid_file(tmp_path: Path):
    # Arrange: write custom valid policy configuration
    valid_data = {
        "damaged": {
            "refund_window_days": 10,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 100.0,
        },
        "wrong_item": {
            "refund_window_days": 15,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 200.0,
        },
        "changed_mind": {
            "refund_window_days": 7,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 50.0,
        },
        "late_delivery": {
            "refund_window_days": 7,
            "eligible_delivery_statuses": ["in_transit"],
            "max_order_amount": 75.0,
        },
        "missing_item": {
            "refund_window_days": 20,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 300.0,
        },
    }
    custom_file = tmp_path / "custom_policies.json"
    custom_file.write_text(json.dumps(valid_data), encoding="utf-8")

    # Act
    config = load_policies(custom_file)

    # Assert
    assert config.damaged.refund_window_days == 10
    assert config.late_delivery.eligible_delivery_statuses == ["in_transit"]


def test_load_policies_raises_file_not_found():
    # Arrange
    missing_path = "nonexistent_policies_file_12345.json"

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        load_policies(missing_path)


def test_load_policies_raises_json_decode_error(tmp_path: Path):
    # Arrange: write malformed JSON
    malformed_file = tmp_path / "malformed.json"
    malformed_file.write_text("{ incomplete json ...", encoding="utf-8")

    # Act & Assert
    with pytest.raises(json.JSONDecodeError):
        load_policies(malformed_file)


def test_load_policies_raises_validation_error_on_missing_category(tmp_path: Path):
    # Arrange: JSON missing "missing_item"
    incomplete_data = {
        "damaged": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 500.0,
        },
        "wrong_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
        "changed_mind": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 200.0,
        },
        "late_delivery": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["in_transit"],
            "max_order_amount": 300.0,
        },
    }
    file_path = tmp_path / "missing_category.json"
    file_path.write_text(json.dumps(incomplete_data), encoding="utf-8")

    # Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        load_policies(file_path)
    assert "missing_item" in str(exc_info.value)


def test_load_policies_raises_validation_error_on_missing_field(tmp_path: Path):
    # Arrange: damaged category missing "max_order_amount"
    invalid_data = {
        "damaged": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
        },
        "wrong_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
        "changed_mind": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 200.0,
        },
        "late_delivery": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["in_transit"],
            "max_order_amount": 300.0,
        },
        "missing_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
    }
    file_path = tmp_path / "missing_field.json"
    file_path.write_text(json.dumps(invalid_data), encoding="utf-8")

    # Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        load_policies(file_path)
    assert "max_order_amount" in str(exc_info.value)


@pytest.mark.parametrize("invalid_days", [0, -1, -30])
def test_load_policies_raises_validation_error_on_non_positive_refund_window(
    tmp_path: Path, invalid_days: int
):
    # Arrange: refund_window_days <= 0
    data = {
        "damaged": {
            "refund_window_days": invalid_days,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 500.0,
        },
        "wrong_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
        "changed_mind": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 200.0,
        },
        "late_delivery": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["in_transit"],
            "max_order_amount": 300.0,
        },
        "missing_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
    }
    file_path = tmp_path / "invalid_window.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    # Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        load_policies(file_path)
    assert "refund_window_days" in str(exc_info.value)


def test_load_policies_raises_validation_error_on_negative_max_amount(tmp_path: Path):
    # Arrange: max_order_amount < 0
    data = {
        "damaged": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": -10.0,
        },
        "wrong_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
        "changed_mind": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 200.0,
        },
        "late_delivery": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["in_transit"],
            "max_order_amount": 300.0,
        },
        "missing_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
    }
    file_path = tmp_path / "negative_amount.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    # Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        load_policies(file_path)
    assert "max_order_amount" in str(exc_info.value)


def test_load_policies_raises_validation_error_on_empty_eligible_statuses(tmp_path: Path):
    # Arrange: empty eligible_delivery_statuses list
    data = {
        "damaged": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": [],
            "max_order_amount": 500.0,
        },
        "wrong_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
        "changed_mind": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 200.0,
        },
        "late_delivery": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["in_transit"],
            "max_order_amount": 300.0,
        },
        "missing_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
    }
    file_path = tmp_path / "empty_statuses.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    # Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        load_policies(file_path)
    assert "eligible_delivery_statuses" in str(exc_info.value)


def test_load_policies_raises_validation_error_on_invalid_types(tmp_path: Path):
    # Arrange: non-numeric string for max_order_amount
    data = {
        "damaged": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": "not-a-number",
        },
        "wrong_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
        "changed_mind": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 200.0,
        },
        "late_delivery": {
            "refund_window_days": 14,
            "eligible_delivery_statuses": ["in_transit"],
            "max_order_amount": 300.0,
        },
        "missing_item": {
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
            "max_order_amount": 1000.0,
        },
    }
    file_path = tmp_path / "invalid_type.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    # Act & Assert
    with pytest.raises(ValidationError) as exc_info:
        load_policies(file_path)
    assert "max_order_amount" in str(exc_info.value)
