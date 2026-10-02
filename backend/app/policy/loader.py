"""Static policy loader module."""

import json
from pathlib import Path
from typing import Any
from app.policy.schema import CategoryPolicy, CategoryPolicyUpdate, PolicyConfig, RefundCategory

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "policies.json"

_active_policy_config: PolicyConfig | None = None


def load_policies(file_path: Path | str | None = None) -> PolicyConfig:
    """Load and validate refund policy configuration from disk.

    Args:
        file_path: Path to the JSON policy file. If None, defaults to app/data/policies.json.

    Returns:
        Validated PolicyConfig instance.

    Raises:
        FileNotFoundError: If the specified policy file does not exist.
        json.JSONDecodeError: If the policy file is not valid JSON.
        pydantic.ValidationError: If the loaded data violates the PolicyConfig schema.
    """
    path = Path(file_path) if file_path is not None else DEFAULT_POLICY_PATH

    if not path.is_file():
        raise FileNotFoundError(f"Policy file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return PolicyConfig.model_validate(data)


def get_active_policies() -> PolicyConfig:
    """Retrieve the currently active in-memory refund policy configuration.

    Initializes from disk policies.json on first invocation if not already loaded.
    """
    global _active_policy_config
    if _active_policy_config is None:
        _active_policy_config = load_policies()
    return _active_policy_config


def reset_active_policies() -> PolicyConfig:
    """Reset active in-memory policies to default disk configuration.

    Useful for test isolation.
    """
    global _active_policy_config
    _active_policy_config = load_policies()
    return _active_policy_config


def update_category_policy(
    category: str,
    update_data: CategoryPolicyUpdate | dict[str, Any],
) -> CategoryPolicy:
    """Validate and update the active policy rules for a given refund category.

    Args:
        category: Refund category name (e.g. 'damaged', 'late_delivery').
        update_data: CategoryPolicyUpdate model or dictionary with updated policy fields.

    Returns:
        Updated CategoryPolicy instance.

    Raises:
        KeyError: If category is not one of the supported refund categories.
        pydantic.ValidationError: If updated thresholds violate validation rules.
    """
    normalized_category = str(category).strip().lower()
    valid_categories = {c.value for c in RefundCategory}
    if normalized_category not in valid_categories:
        raise KeyError(
            f"Category '{category}' is not a valid refund category. "
            f"Valid categories are: {', '.join(sorted(valid_categories))}"
        )

    active_config = get_active_policies()
    current_policy = getattr(active_config, normalized_category)

    if isinstance(update_data, CategoryPolicyUpdate):
        update_dict = update_data.model_dump(exclude_unset=True)
    elif isinstance(update_data, dict):
        validated_update = CategoryPolicyUpdate.model_validate(update_data)
        update_dict = validated_update.model_dump(exclude_unset=True)
    else:
        raise TypeError(
            f"Expected CategoryPolicyUpdate or dict, got {type(update_data).__name__}"
        )

    merged = current_policy.model_dump()
    merged.update(update_dict)

    if "return_window_days" in update_dict:
        merged["refund_window_days"] = update_dict["return_window_days"]
    elif "refund_window_days" in update_dict:
        merged["return_window_days"] = update_dict["refund_window_days"]

    if "max_refund_amount" in update_dict:
        merged["max_order_amount"] = update_dict["max_refund_amount"]
    elif "max_order_amount" in update_dict:
        merged["max_refund_amount"] = update_dict["max_order_amount"]

    updated_policy = CategoryPolicy.model_validate(merged)
    setattr(active_config, normalized_category, updated_policy)
    return updated_policy
