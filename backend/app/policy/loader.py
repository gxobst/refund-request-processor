"""Static policy loader module."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid
from app.policy.schema import (
    CategoryPolicy,
    CategoryPolicyUpdate,
    PolicyAuditEntry,
    PolicyConfig,
    PolicyFieldChange,
    RefundCategory,
)

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "policies.json"

_active_policy_config: PolicyConfig | None = None
_policy_audit_history: list[PolicyAuditEntry] = []



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
    global _active_policy_config, _policy_audit_history
    _active_policy_config = load_policies()
    _policy_audit_history = []
    return _active_policy_config


def update_category_policy(
    category: str,
    update_data: CategoryPolicyUpdate | dict[str, Any],
    operator_id: str = "supervisor",
) -> CategoryPolicy:
    """Validate and update the active policy rules for a given refund category.

    Args:
        category: Refund category name (e.g. 'damaged', 'late_delivery').
        update_data: CategoryPolicyUpdate model or dictionary with updated policy fields.
        operator_id: Operator or role identifier performing the change (default: 'supervisor').

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
    previous_state = current_policy.model_dump()

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
    new_state = updated_policy.model_dump()

    changes: dict[str, PolicyFieldChange | dict[str, Any]] = {}
    for key, new_val in new_state.items():
        old_val = previous_state.get(key)
        if old_val != new_val:
            changes[key] = PolicyFieldChange(old_value=old_val, new_value=new_val)

    audit_entry = PolicyAuditEntry(
        audit_id=f"audit_{uuid.uuid4().hex[:10]}",
        category=normalized_category,
        timestamp=datetime.now(timezone.utc).isoformat(),
        operator_id=operator_id or "supervisor",
        changes=changes,
        previous_state=previous_state,
        action="update",
    )
    _policy_audit_history.append(audit_entry)

    setattr(active_config, normalized_category, updated_policy)
    return updated_policy


def get_policy_history(category: str | None = None) -> list[PolicyAuditEntry]:
    """Retrieve policy audit entries sorted reverse chronological (newest first).

    Args:
        category: Optional category filter.

    Returns:
        List of PolicyAuditEntry instances.

    Raises:
        KeyError: If category is specified but invalid.
    """
    if category is not None:
        normalized = str(category).strip().lower()
        valid_categories = {c.value for c in RefundCategory}
        if normalized not in valid_categories:
            raise KeyError(
                f"Category '{category}' is not a valid refund category. "
                f"Valid categories are: {', '.join(sorted(valid_categories))}"
            )
        entries = [e for e in _policy_audit_history if e.category == normalized]
    else:
        entries = list(_policy_audit_history)

    return sorted(entries, key=lambda e: e.timestamp, reverse=True)


def rollback_policy(
    category: str,
    audit_id: str | None = None,
    operator_id: str = "supervisor",
) -> tuple[CategoryPolicy, PolicyAuditEntry]:
    """Restore a category policy to its state before a specific audit change or to the immediate predecessor.

    Args:
        category: Refund category name.
        audit_id: Optional ID of the audit entry whose previous_state should be restored.
        operator_id: Operator performing rollback (default: 'supervisor').

    Returns:
        Tuple of (restored CategoryPolicy, newly created rollback PolicyAuditEntry).

    Raises:
        KeyError: If category is invalid.
        ValueError: If audit_id does not exist or if no history exists for the category.
    """
    normalized_category = str(category).strip().lower()
    valid_categories = {c.value for c in RefundCategory}
    if normalized_category not in valid_categories:
        raise KeyError(
            f"Category '{category}' is not a valid refund category. "
            f"Valid categories are: {', '.join(sorted(valid_categories))}"
        )

    category_entries = [e for e in _policy_audit_history if e.category == normalized_category]
    if not category_entries:
        raise ValueError(f"No audit history found for category '{category}' to rollback")

    target_entry: PolicyAuditEntry | None = None
    if audit_id is not None:
        for entry in reversed(category_entries):
            if entry.audit_id == audit_id:
                target_entry = entry
                break
        if target_entry is None:
            raise ValueError(f"Audit entry '{audit_id}' not found for category '{category}'")
    else:
        target_entry = category_entries[-1]

    active_config = get_active_policies()
    current_policy = getattr(active_config, normalized_category)
    current_state = current_policy.model_dump()
    restored_state = target_entry.previous_state

    updated_policy = CategoryPolicy.model_validate(restored_state)
    setattr(active_config, normalized_category, updated_policy)

    new_state = updated_policy.model_dump()
    changes: dict[str, PolicyFieldChange | dict[str, Any]] = {}
    for key, new_val in new_state.items():
        old_val = current_state.get(key)
        if old_val != new_val:
            changes[key] = PolicyFieldChange(old_value=old_val, new_value=new_val)

    rollback_entry = PolicyAuditEntry(
        audit_id=f"audit_{uuid.uuid4().hex[:10]}",
        category=normalized_category,
        timestamp=datetime.now(timezone.utc).isoformat(),
        operator_id=operator_id or "supervisor",
        changes=changes,
        previous_state=current_state,
        action="rollback",
    )
    _policy_audit_history.append(rollback_entry)

    return updated_policy, rollback_entry

