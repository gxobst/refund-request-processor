"""Deterministic policy evaluation engine for refund requests."""

from datetime import date, datetime
from typing import Any
from pydantic import BaseModel

from app.policy.loader import get_active_policies
from app.policy.schema import CategoryPolicy, PolicyConfig, PolicyEvaluationResult


def _parse_date(val: Any) -> date | None:
    """Parse various date representations into a datetime.date object."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        # Support ISO formats: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                pass
    return None


def evaluate_policy(
    category: str,
    order: dict[str, Any] | BaseModel,
    policy: CategoryPolicy | PolicyConfig | dict[str, Any] | None = None,
    evaluation_date: date | datetime | str | None = None,
) -> PolicyEvaluationResult:
    """Evaluate a refund request against category policy rules deterministically.

    Args:
        category: Refund reason category string.
        order: Order data dict or Pydantic model.
        policy: CategoryPolicy instance, complete PolicyConfig, or policy dictionary.
            Defaults to active in-memory configuration from get_active_policies().
        evaluation_date: Date to evaluate against. Defaults to date.today().

    Returns:
        PolicyEvaluationResult with status ('pass', 'fail', 'ambiguous'),
        passed_rules, failed_rules, details, and matched_policy_rule.
    """
    if policy is None:
        policy = get_active_policies()

    # 1. Resolve matching policy rule
    matched_rule: CategoryPolicy | dict[str, Any] | None = None

    if isinstance(policy, CategoryPolicy):
        matched_rule = policy
    elif isinstance(policy, PolicyConfig):
        matched_rule = policy.get(category)
    elif isinstance(policy, dict):
        if category in policy:
            item = policy[category]
            if isinstance(item, dict):
                try:
                    matched_rule = CategoryPolicy.model_validate(item)
                except Exception:
                    matched_rule = item
            elif isinstance(item, CategoryPolicy):
                matched_rule = item
            else:
                matched_rule = item
        elif "refund_window_days" in policy and "eligible_delivery_statuses" in policy:
            try:
                matched_rule = CategoryPolicy.model_validate(policy)
            except Exception:
                matched_rule = policy

    if matched_rule is None:
        return PolicyEvaluationResult(
            status="ambiguous",
            passed_rules=[],
            failed_rules=[],
            details=f"Unknown or unmapped policy category: '{category}'",
            matched_policy_rule=None,
        )

    # 2. Extract order fields
    order_data: dict[str, Any]
    if isinstance(order, BaseModel):
        order_data = order.model_dump()
    elif isinstance(order, dict):
        order_data = order
    else:
        order_data = {}

    # 3. Validate required order fields
    missing_fields: list[str] = []

    # Check order_amount
    amount_raw = order_data.get("order_amount")
    amount: float | None = None
    if amount_raw is None or (isinstance(amount_raw, str) and not str(amount_raw).strip()):
        missing_fields.append("order_amount")
    else:
        try:
            amount = float(amount_raw)
            if amount < 0:
                missing_fields.append("order_amount (must be non-negative)")
        except (ValueError, TypeError):
            missing_fields.append("order_amount (must be numeric)")

    # Check delivery_status
    status_raw = order_data.get("delivery_status")
    delivery_status: str | None = None
    if status_raw is None or (isinstance(status_raw, str) and not str(status_raw).strip()):
        missing_fields.append("delivery_status")
    else:
        delivery_status = str(status_raw).strip().lower()

    # Check dates: prefer delivery_date, fallback to purchase_date
    delivery_date_raw = order_data.get("delivery_date")
    purchase_date_raw = order_data.get("purchase_date")
    target_date: date | None = None

    if delivery_date_raw is not None and str(delivery_date_raw).strip():
        target_date = _parse_date(delivery_date_raw)
        if target_date is None:
            missing_fields.append("delivery_date (invalid format)")
    elif purchase_date_raw is not None and str(purchase_date_raw).strip():
        target_date = _parse_date(purchase_date_raw)
        if target_date is None:
            missing_fields.append("purchase_date (invalid format)")
    else:
        missing_fields.append("delivery_date/purchase_date")

    if missing_fields or amount is None or delivery_status is None or target_date is None:
        return PolicyEvaluationResult(
            status="ambiguous",
            passed_rules=[],
            failed_rules=[],
            details=f"Missing or invalid order fields: {', '.join(missing_fields)}",
            matched_policy_rule=matched_rule,
        )

    # 4. Resolve evaluation date
    eval_date: date
    if evaluation_date is None:
        eval_date = date.today()
    else:
        parsed_eval = _parse_date(evaluation_date)
        eval_date = parsed_eval if parsed_eval is not None else date.today()

    # 5. Evaluate policy dimensions in canonical order
    passed_rules: list[str] = []
    failed_rules: list[str] = []

    # Dimension 1: refund_window_days
    window_days = (
        matched_rule.refund_window_days
        if hasattr(matched_rule, "refund_window_days")
        else int(matched_rule["refund_window_days"])
    )
    elapsed_days = (eval_date - target_date).days
    if elapsed_days <= window_days:
        passed_rules.append("refund_window_days")
    else:
        failed_rules.append("refund_window_days")

    # Dimension 2: eligible_delivery_statuses
    eligible_statuses = (
        matched_rule.eligible_delivery_statuses
        if hasattr(matched_rule, "eligible_delivery_statuses")
        else matched_rule["eligible_delivery_statuses"]
    )
    eligible_lower = [str(s).strip().lower() for s in eligible_statuses]
    if delivery_status in eligible_lower:
        passed_rules.append("eligible_delivery_statuses")
    else:
        failed_rules.append("eligible_delivery_statuses")

    # Dimension 3: max_order_amount
    max_amount = (
        matched_rule.max_order_amount
        if hasattr(matched_rule, "max_order_amount")
        else float(matched_rule["max_order_amount"])
    )
    if amount <= max_amount:
        passed_rules.append("max_order_amount")
    else:
        failed_rules.append("max_order_amount")

    # 6. Determine final result status
    if failed_rules == ["max_order_amount"]:
        status = "ambiguous"
        details = (
            f"Order amount (${amount:.2f}) exceeds maximum threshold "
            f"(${max_amount:.2f}); requires supervisor escalation."
        )
    elif failed_rules:
        status = "fail"
        details = f"Evaluation failed for rules: {', '.join(failed_rules)}"
    else:
        status = "pass"
        details = "All policy rules passed."

    return PolicyEvaluationResult(
        status=status,
        passed_rules=passed_rules,
        failed_rules=failed_rules,
        details=details,
        matched_policy_rule=matched_rule,
    )
