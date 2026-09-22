"""Unit tests for Policy Checker Agent and deterministic bypass behavior."""

from datetime import date
from unittest.mock import MagicMock
from langchain_core.runnables import RunnableLambda
import pytest

from app.agents.policy_checker import check_policy, policy_checker_node
from app.schemas.policy_checker import PolicyCheckerOutput


def make_mock_llm(output: PolicyCheckerOutput) -> MagicMock:
    """Helper to create a mocked BaseChatModel returning a structured PolicyCheckerOutput."""
    mock = MagicMock()
    mock.with_structured_output.return_value = RunnableLambda(lambda _: output)
    return mock


def test_check_policy_deterministic_pass_bypasses_llm():
    # Arrange: eligible order passing all rules
    order = {
        "order_id": "ORD-PASS-1",
        "order_amount": 150.0,
        "delivery_status": "delivered",
        "delivery_date": date.today().isoformat(),
    }
    mock_llm = MagicMock()

    # Act
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    # Assert
    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "pass"
    assert len(result.passed_rules) == 3
    assert result.failed_rules == []
    assert "passed" in result.policy_reasoning.lower()

    # Verify LLM was NOT called
    mock_llm.with_structured_output.assert_not_called()


def test_check_policy_deterministic_fail_bypasses_llm():
    # Arrange: order exceeding maximum amount limit ($500 for damaged)
    order = {
        "order_id": "ORD-FAIL-1",
        "order_amount": 950.0,
        "delivery_status": "delivered",
        "delivery_date": date.today().isoformat(),
    }
    mock_llm = MagicMock()

    # Act
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    # Assert
    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "fail"
    assert "max_order_amount" in result.failed_rules
    assert "fail" in result.policy_reasoning.lower()

    # Verify LLM was NOT called
    mock_llm.with_structured_output.assert_not_called()


def test_check_policy_ambiguous_invokes_llm():
    # Arrange: order missing required fields (ambiguous condition)
    order = {
        "order_id": "ORD-AMB-1",
        "order_amount": 200.0,
        # missing delivery_status and dates
    }
    expected_output = PolicyCheckerOutput(
        policy_status="ambiguous",
        passed_rules=[],
        failed_rules=[],
        policy_reasoning="Missing required delivery and status information; requires human escalation.",
    )
    mock_llm = make_mock_llm(expected_output)

    # Act
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    # Assert
    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "ambiguous"
    assert "escalation" in result.policy_reasoning.lower()

    # Verify LLM WAS called
    mock_llm.with_structured_output.assert_called_once()


def test_check_policy_ambiguous_resolved_by_llm():
    # Arrange: ambiguous date format that the LLM successfully evaluates as pass
    order = {
        "order_id": "ORD-AMB-2",
        "order_amount": 100.0,
        "delivery_status": "delivered",
        "delivery_date": "yesterday afternoon",  # unparseable by deterministic engine
    }
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="LLM confirmed delivery occurred yesterday, well within the 30-day window.",
    )
    mock_llm = make_mock_llm(expected_output)

    # Act
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    # Assert
    assert result.policy_status == "pass"
    assert "yesterday" in result.policy_reasoning
    mock_llm.with_structured_output.assert_called_once()


def test_policy_checker_node_contract():
    # Arrange: clear-cut passing order in state
    state = {
        "refund_id": "ref_node_1",
        "category": "damaged",
        "order": {
            "order_id": "ORD-NODE-1",
            "order_amount": 120.0,
            "delivery_status": "delivered",
            "delivery_date": date.today().isoformat(),
        },
    }

    # Act
    node_result = policy_checker_node(state)

    # Assert
    assert node_result["policy_status"] == "pass"
    assert isinstance(node_result["matched_policy_rule"], dict)
    assert node_result["matched_policy_rule"]["max_order_amount"] == 500.0
    assert "passed_rules" in node_result
    assert "failed_rules" in node_result
    assert node_result["failed_rules"] == []
    assert "policy_reasoning" in node_result


def test_policy_checker_node_ambiguous_state():
    # Arrange: incomplete order triggering ambiguity
    state = {
        "refund_id": "ref_node_2",
        "category": "damaged",
        "order": {
            "order_id": "ORD-NODE-2",
            "order_amount": 120.0,
            # missing delivery_status
        },
    }
    expected_output = PolicyCheckerOutput(
        policy_status="ambiguous",
        passed_rules=[],
        failed_rules=[],
        policy_reasoning="Delivery status missing from order record.",
    )
    mock_llm = make_mock_llm(expected_output)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.policy_checker.get_bedrock_llm", lambda: mock_llm)
        node_result = policy_checker_node(state)

    # Assert
    assert node_result["policy_status"] == "ambiguous"
    assert "missing" in node_result["policy_reasoning"].lower()
