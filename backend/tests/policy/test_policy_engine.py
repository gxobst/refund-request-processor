"""Unit tests for deterministic refund policy evaluation engine."""

from datetime import date, timedelta
import pytest
from pydantic import BaseModel

from app.policy.engine import evaluate_policy
from app.policy.loader import load_policies
from app.policy.schema import CategoryPolicy, PolicyConfig, PolicyEvaluationResult


class MockOrder(BaseModel):
    order_id: str
    item: str
    purchase_date: str
    order_amount: float
    delivery_date: str | None = None
    delivery_status: str


@pytest.fixture
def sample_policy_config() -> PolicyConfig:
    return load_policies()


@pytest.fixture
def damaged_policy() -> CategoryPolicy:
    return CategoryPolicy(
        refund_window_days=30,
        eligible_delivery_statuses=["delivered"],
        max_order_amount=500.0,
    )


def test_evaluate_policy_all_rules_pass(damaged_policy: CategoryPolicy):
    # Arrange: eligible order within window, correct status, under amount limit
    eval_date = date(2026, 9, 20)
    order = {
        "order_id": "ORD-001",
        "order_amount": 250.0,
        "delivery_status": "delivered",
        "delivery_date": "2026-09-01",  # 19 days elapsed <= 30
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert isinstance(result, PolicyEvaluationResult)
    assert result.status == "pass"
    assert result.failed_rules == []
    assert result.passed_rules == [
        "refund_window_days",
        "eligible_delivery_statuses",
        "max_order_amount",
    ]
    assert result.matched_policy_rule == damaged_policy


def test_window_exact_boundary_passes(damaged_policy: CategoryPolicy):
    # Arrange: exactly 30 days elapsed
    eval_date = date(2026, 9, 30)
    delivery_date = eval_date - timedelta(days=30)
    order = {
        "order_id": "ORD-002",
        "order_amount": 100.0,
        "delivery_status": "delivered",
        "delivery_date": delivery_date.isoformat(),
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "pass"
    assert "refund_window_days" in result.passed_rules
    assert result.failed_rules == []


def test_window_exceeded_by_one_day_fails(damaged_policy: CategoryPolicy):
    # Arrange: exactly 31 days elapsed
    eval_date = date(2026, 9, 30)
    delivery_date = eval_date - timedelta(days=31)
    order = {
        "order_id": "ORD-003",
        "order_amount": 100.0,
        "delivery_status": "delivered",
        "delivery_date": delivery_date.isoformat(),
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "fail"
    assert "refund_window_days" in result.failed_rules
    assert "eligible_delivery_statuses" in result.passed_rules
    assert "max_order_amount" in result.passed_rules


def test_fallback_to_purchase_date_when_delivery_date_missing(damaged_policy: CategoryPolicy):
    # Arrange: delivery_date is None, purchase_date is 10 days before eval_date
    eval_date = date(2026, 9, 15)
    order = {
        "order_id": "ORD-004",
        "order_amount": 300.0,
        "delivery_status": "delivered",
        "purchase_date": "2026-09-05",
        "delivery_date": None,
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "pass"
    assert "refund_window_days" in result.passed_rules


def test_amount_exact_boundary_passes(damaged_policy: CategoryPolicy):
    # Arrange: order_amount exactly equals max_order_amount (500.0)
    eval_date = date(2026, 9, 10)
    order = {
        "order_id": "ORD-005",
        "order_amount": 500.0,
        "delivery_status": "delivered",
        "delivery_date": "2026-09-05",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "pass"
    assert "max_order_amount" in result.passed_rules


def test_amount_exceeded_fails(damaged_policy: CategoryPolicy):
    # Arrange: order_amount 500.01 exceeds 500.0 limit
    eval_date = date(2026, 9, 10)
    order = {
        "order_id": "ORD-006",
        "order_amount": 500.01,
        "delivery_status": "delivered",
        "delivery_date": "2026-09-05",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "fail"
    assert "max_order_amount" in result.failed_rules


def test_delivery_status_ineligible_fails(damaged_policy: CategoryPolicy):
    # Arrange: delivery_status is 'cancelled' (not in ['delivered'])
    eval_date = date(2026, 9, 10)
    order = {
        "order_id": "ORD-007",
        "order_amount": 100.0,
        "delivery_status": "cancelled",
        "delivery_date": "2026-09-05",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "fail"
    assert "eligible_delivery_statuses" in result.failed_rules


def test_multiple_eligible_statuses_pass(sample_policy_config: PolicyConfig):
    # Arrange: late_delivery allows both 'in_transit' and 'delivered'
    eval_date = date(2026, 9, 10)
    order_in_transit = {
        "order_id": "ORD-008",
        "order_amount": 150.0,
        "delivery_status": "in_transit",
        "purchase_date": "2026-09-01",
    }
    order_delivered = {
        "order_id": "ORD-009",
        "order_amount": 150.0,
        "delivery_status": "delivered",
        "purchase_date": "2026-09-01",
    }

    # Act
    res_transit = evaluate_policy(
        category="late_delivery",
        order=order_in_transit,
        policy=sample_policy_config,
        evaluation_date=eval_date,
    )
    res_delivered = evaluate_policy(
        category="late_delivery",
        order=order_delivered,
        policy=sample_policy_config,
        evaluation_date=eval_date,
    )

    # Assert
    assert res_transit.status == "pass"
    assert "eligible_delivery_statuses" in res_transit.passed_rules
    assert res_delivered.status == "pass"
    assert "eligible_delivery_statuses" in res_delivered.passed_rules


def test_multiple_rules_fail(damaged_policy: CategoryPolicy):
    # Arrange: both amount exceeds limit and delivery status is ineligible
    eval_date = date(2026, 9, 10)
    order = {
        "order_id": "ORD-010",
        "order_amount": 750.0,
        "delivery_status": "returned",
        "delivery_date": "2026-09-05",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "fail"
    assert "max_order_amount" in result.failed_rules
    assert "eligible_delivery_statuses" in result.failed_rules
    assert "refund_window_days" in result.passed_rules


def test_all_three_rules_fail(damaged_policy: CategoryPolicy):
    # Arrange: window exceeded (35 days), status ineligible ('cancelled'), amount exceeded (999.0)
    eval_date = date(2026, 9, 30)
    order = {
        "order_id": "ORD-011",
        "order_amount": 999.0,
        "delivery_status": "cancelled",
        "delivery_date": "2026-08-20",  # 41 days elapsed
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=eval_date,
    )

    # Assert
    assert result.status == "fail"
    assert len(result.failed_rules) == 3
    assert result.passed_rules == []
    assert set(result.failed_rules) == {
        "refund_window_days",
        "eligible_delivery_statuses",
        "max_order_amount",
    }


def test_missing_order_amount_returns_ambiguous(damaged_policy: CategoryPolicy):
    # Arrange: order_amount is None
    order = {
        "order_id": "ORD-012",
        "order_amount": None,
        "delivery_status": "delivered",
        "delivery_date": "2026-09-01",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=date(2026, 9, 10),
    )

    # Assert
    assert result.status == "ambiguous"
    assert "order_amount" in str(result.details)
    assert result.passed_rules == []
    assert result.failed_rules == []


def test_missing_delivery_status_returns_ambiguous(damaged_policy: CategoryPolicy):
    # Arrange: delivery_status missing
    order = {
        "order_id": "ORD-013",
        "order_amount": 150.0,
        "delivery_date": "2026-09-01",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=date(2026, 9, 10),
    )

    # Assert
    assert result.status == "ambiguous"
    assert "delivery_status" in str(result.details)


def test_missing_dates_returns_ambiguous(damaged_policy: CategoryPolicy):
    # Arrange: neither delivery_date nor purchase_date provided
    order = {
        "order_id": "ORD-014",
        "order_amount": 150.0,
        "delivery_status": "delivered",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=date(2026, 9, 10),
    )

    # Assert
    assert result.status == "ambiguous"
    assert "date" in str(result.details).lower()


def test_invalid_date_format_returns_ambiguous(damaged_policy: CategoryPolicy):
    # Arrange: unparseable delivery_date
    order = {
        "order_id": "ORD-015",
        "order_amount": 150.0,
        "delivery_status": "delivered",
        "delivery_date": "invalid-date-string",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=date(2026, 9, 10),
    )

    # Assert
    assert result.status == "ambiguous"
    assert "delivery_date" in str(result.details)


def test_unknown_category_returns_ambiguous(sample_policy_config: PolicyConfig):
    # Arrange: category not in policy
    order = {
        "order_id": "ORD-016",
        "order_amount": 150.0,
        "delivery_status": "delivered",
        "delivery_date": "2026-09-01",
    }

    # Act
    result = evaluate_policy(
        category="unsupported_category",
        order=order,
        policy=sample_policy_config,
        evaluation_date=date(2026, 9, 10),
    )

    # Assert
    assert result.status == "ambiguous"
    assert result.matched_policy_rule is None
    assert "unsupported_category" in str(result.details)


def test_evaluate_policy_with_pydantic_order_model(damaged_policy: CategoryPolicy):
    # Arrange: order passed as BaseModel instance
    order = MockOrder(
        order_id="ORD-017",
        item="Wireless Headphones",
        purchase_date="2026-09-01",
        order_amount=199.99,
        delivery_date="2026-09-05",
        delivery_status="delivered",
    )

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=damaged_policy,
        evaluation_date=date(2026, 9, 15),
    )

    # Assert
    assert result.status == "pass"
    assert len(result.passed_rules) == 3


def test_evaluate_policy_with_dict_policy():
    # Arrange: policy passed as dictionary conforming to testing guidelines Section 4
    policy_dict = {
        "damaged": {
            "max_order_amount": 500.0,
            "refund_window_days": 30,
            "eligible_delivery_statuses": ["delivered"],
        }
    }
    order = {
        "order_id": "ORD-018",
        "order_amount": 650.0,
        "delivery_status": "delivered",
        "purchase_date": "2026-09-01",
    }

    # Act
    result = evaluate_policy(
        category="damaged",
        order=order,
        policy=policy_dict,
        evaluation_date=date(2026, 9, 10),
    )

    # Assert
    assert result.status == "fail"
    assert "max_order_amount" in result.failed_rules
