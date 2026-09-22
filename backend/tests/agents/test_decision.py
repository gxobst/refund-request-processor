"""Unit tests for Decision Agent and decision node."""

import pytest

from app.agents.decision import decision_node, make_decision
from app.schemas.decision import DecisionOutput


def test_make_decision_auto_approve():
    # Arrange: valid category and passing policy
    matched_rule = {
        "refund_window_days": 30,
        "eligible_delivery_statuses": ["delivered"],
        "max_order_amount": 500.0,
    }

    # Act
    output = make_decision(
        category="damaged",
        classification_confidence=0.92,
        policy_status="pass",
        matched_policy_rule=matched_rule,
        failed_rules=[],
        policy_reasoning="All policy rules passed.",
        is_low_confidence=False,
    )

    # Assert
    assert isinstance(output, DecisionOutput)
    assert output.decision == "auto_approve"
    assert output.confidence_score == 0.92
    assert "approved" in output.reasoning.lower()
    assert output.matched_policy_rule == matched_rule


def test_make_decision_deny():
    # Arrange: failing policy due to exceeded amount
    matched_rule = {
        "refund_window_days": 30,
        "eligible_delivery_statuses": ["delivered"],
        "max_order_amount": 500.0,
    }

    # Act
    output = make_decision(
        category="damaged",
        classification_confidence=0.85,
        policy_status="fail",
        matched_policy_rule=matched_rule,
        failed_rules=["max_order_amount"],
        policy_reasoning="Order amount exceeded maximum limit.",
        is_low_confidence=False,
    )

    # Assert
    assert isinstance(output, DecisionOutput)
    assert output.decision == "deny"
    assert output.confidence_score == 0.85
    assert "denied" in output.reasoning.lower()
    assert "max_order_amount" in output.reasoning


def test_escalation_trigger_1_low_confidence():
    # Arrange: classification confidence below 0.70 threshold
    output = make_decision(
        category="damaged",
        classification_confidence=0.55,
        policy_status="pass",
        matched_policy_rule=None,
        failed_rules=[],
        policy_reasoning="All policy rules passed.",
        is_low_confidence=True,
    )

    # Assert
    assert output.decision == "escalate"
    assert "confidence" in output.reasoning.lower()
    assert output.confidence_score == 0.55


def test_escalation_trigger_2_ambiguous_policy():
    # Arrange: policy evaluation returned ambiguous
    output = make_decision(
        category="damaged",
        classification_confidence=0.95,
        policy_status="ambiguous",
        matched_policy_rule=None,
        failed_rules=[],
        policy_reasoning="Date cannot be definitively verified.",
    )

    # Assert
    assert output.decision == "escalate"
    assert "ambiguity" in output.reasoning.lower()


def test_escalation_trigger_3_missing_order_data():
    # Arrange: missing required order data flag set
    output = make_decision(
        category="wrong_item",
        classification_confidence=0.90,
        policy_status="pass",
        matched_policy_rule=None,
        failed_rules=[],
        policy_reasoning="All policy rules passed.",
        missing_order_data=True,
    )

    # Assert
    assert output.decision == "escalate"
    assert "missing" in output.reasoning.lower()


def test_escalation_trigger_4_policy_conflict():
    # Arrange: policy conflict flag set
    output = make_decision(
        category="damaged",
        classification_confidence=0.90,
        policy_status="pass",
        matched_policy_rule=None,
        failed_rules=[],
        policy_reasoning="All policy rules passed.",
        policy_conflict=True,
    )

    # Assert
    assert output.decision == "escalate"
    assert "contradictory" in output.reasoning.lower() or "conflict" in output.reasoning.lower()


def test_decision_node_completed_auto_approve():
    # Arrange: passing workflow state
    state = {
        "category": "damaged",
        "classification_confidence": 0.95,
        "is_low_confidence": False,
        "policy_status": "pass",
        "matched_policy_rule": {"max_order_amount": 500},
        "failed_rules": [],
        "policy_reasoning": "Within policy",
    }

    # Act
    node_res = decision_node(state)

    # Assert
    assert node_res["decision"] == "auto_approve"
    assert node_res["status"] == "completed"
    assert node_res["confidence_score"] == 0.95
    assert "approved" in node_res["reasoning"].lower()


def test_decision_node_completed_deny():
    # Arrange: failing workflow state
    state = {
        "category": "damaged",
        "classification_confidence": 0.88,
        "is_low_confidence": False,
        "policy_status": "fail",
        "matched_policy_rule": {"max_order_amount": 500},
        "failed_rules": ["refund_window_days"],
        "policy_reasoning": "Window expired",
    }

    # Act
    node_res = decision_node(state)

    # Assert
    assert node_res["decision"] == "deny"
    assert node_res["status"] == "completed"
    assert "denied" in node_res["reasoning"].lower()


def test_decision_node_escalated_state():
    # Arrange: low-confidence workflow state
    state = {
        "category": "damaged",
        "classification_confidence": 0.40,
        "is_low_confidence": True,
        "policy_status": "pass",
        "matched_policy_rule": None,
        "failed_rules": [],
        "policy_reasoning": "",
    }

    # Act
    node_res = decision_node(state)

    # Assert
    assert node_res["decision"] == "escalate"
    assert node_res["status"] == "escalated"
    assert "confidence" in node_res["reasoning"].lower()
