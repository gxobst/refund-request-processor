"""Unit tests for Policy Checker Agent and deterministic bypass behavior."""

from datetime import date
from typing import Any
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, ToolMessage
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


class MockToolCallingLLM:
    """Mock LLM supporting tool binding, multi-turn tool calling, and structured output."""

    def __init__(
        self,
        responses: list[AIMessage],
        final_output: PolicyCheckerOutput,
    ) -> None:
        self.responses = list(responses)
        self.final_output = final_output
        self.invocations: list[list[Any]] = []
        self.bound_tools: list[Any] = []

    def bind_tools(self, tools: list[Any]) -> "MockToolCallingLLM":
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        self.invocations.append(list(messages))
        if self.responses:
            return self.responses.pop(0)
        return AIMessage(content="Evaluation complete.", tool_calls=[])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return RunnableLambda(lambda _: self.final_output)


def test_check_policy_late_delivery_invokes_carrier_tool_and_passes():
    # Arrange: late_delivery order within $300 limit
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
        "purchase_date": "2026-09-01",
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1005"},
            "id": "call_trk_1005",
        }],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Carrier tracking confirmed shipment is delayed in transit past expected delivery date.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    # Act
    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    # Assert
    assert result.policy_status == "pass"
    assert "tracking" in result.policy_reasoning.lower()
    # Verify carrier tool was called and ToolMessage was passed back in turn 2
    assert len(mock_llm.invocations) >= 2
    tool_messages = [m for m in mock_llm.invocations[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_trk_1005"
    assert "TRK-1005" in tool_messages[0].content
    assert "in_transit" in tool_messages[0].content


def test_check_policy_dispute_status_under_review_returns_ambiguous_or_fail():
    # Arrange: order with missing fields triggering LLM external verification
    order = {
        "order_id": "ORD-1006",
        "order_amount": 45.0,
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_payment_transaction",
            "args": {"order_id": "ORD-1006"},
            "id": "call_pay_1006",
        }],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="ambiguous",
        passed_rules=[],
        failed_rules=[],
        policy_reasoning="Payment transaction has dispute_status='under_review'; requires human resolution.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    # Act
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    # Assert
    assert result.policy_status in ("ambiguous", "fail")
    assert "dispute" in result.policy_reasoning.lower() or "under_review" in result.policy_reasoning.lower()
    assert len(mock_llm.invocations) >= 2
    tool_messages = [m for m in mock_llm.invocations[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_pay_1006"
    assert "under_review" in tool_messages[0].content


def test_check_policy_parallel_tool_calls_in_single_turn():
    # Arrange: parallel tool calls emitted by model
    order = {
        "order_id": "ORD-1001",
        "order_amount": 150.0,
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "query_carrier_tracking",
                "args": {"tracking_number": "TRK-1001"},
                "id": "call_trk_parallel",
            },
            {
                "name": "query_payment_transaction",
                "args": {"order_id": "ORD-1001"},
                "id": "call_pay_parallel",
            },
        ],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Both carrier and payment verifications passed cleanly.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    # Act
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    # Assert
    assert result.policy_status == "pass"
    assert len(mock_llm.invocations) >= 2
    tool_messages = [m for m in mock_llm.invocations[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 2
    call_ids = {m.tool_call_id for m in tool_messages}
    assert call_ids == {"call_trk_parallel", "call_pay_parallel"}


def test_check_policy_unknown_tool_handled_gracefully():
    # Arrange: LLM produces a non-existent tool call
    order = {
        "order_id": "ORD-AMB-UNK",
        "order_amount": 100.0,
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "non_existent_inventory_service",
            "args": {"sku": "SKU-99"},
            "id": "call_unk_1",
        }],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="ambiguous",
        passed_rules=[],
        failed_rules=[],
        policy_reasoning="Tool was unrecognized; escalating to human review.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    # Act
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    # Assert: should not raise exception, and error ToolMessage should be passed to model
    assert isinstance(result, PolicyCheckerOutput)
    tool_messages = [m for m in mock_llm.invocations[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "not found" in tool_messages[0].content.lower()
    assert "Available tools" in tool_messages[0].content


def test_check_policy_tool_execution_exception_handled_safely():
    # Arrange: custom tool that throws RuntimeError
    from langchain_core.tools import tool

    @tool("failing_tool")
    def failing_tool(query: str) -> str:
        """A tool that raises an exception."""
        raise RuntimeError("Remote API gateway timeout 504")

    order = {
        "order_id": "ORD-ERR-1",
        "order_amount": 100.0,
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "failing_tool",
            "args": {"query": "test"},
            "id": "call_err_1",
        }],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="ambiguous",
        passed_rules=[],
        failed_rules=[],
        policy_reasoning="Tool call failed due to timeout; escalating.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    # Act: execute with failing tool
    result = check_policy(category="damaged", order=order, llm=mock_llm, tools=[failing_tool])

    # Assert: error caught and ToolMessage constructed
    assert isinstance(result, PolicyCheckerOutput)
    tool_messages = [m for m in mock_llm.invocations[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "Tool execution error" in tool_messages[0].content
    assert "Remote API gateway timeout 504" in tool_messages[0].content


def test_check_policy_max_tool_iterations_enforced():
    # Arrange: LLM that loops infinitely returning tool calls
    order = {
        "order_id": "ORD-LOOP-1",
        "order_amount": 100.0,
    }
    infinite_tool_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1001"},
            "id": "call_loop",
        }],
    )

    class InfiniteLoopLLM:
        def __init__(self, output: PolicyCheckerOutput) -> None:
            self.output = output
            self.invoke_count = 0

        def bind_tools(self, tools: list[Any]) -> "InfiniteLoopLLM":
            return self

        def invoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
            self.invoke_count += 1
            return infinite_tool_call

        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            return RunnableLambda(lambda _: self.output)

    expected_output = PolicyCheckerOutput(
        policy_status="ambiguous",
        passed_rules=[],
        failed_rules=[],
        policy_reasoning="Runaway loop terminated by max_tool_iterations limit.",
    )
    loop_llm = InfiniteLoopLLM(expected_output)

    # Act: max_tool_iterations=3
    result = check_policy(category="damaged", order=order, llm=loop_llm, max_tool_iterations=3)

    # Assert: invoke loop stopped exactly at 3 iterations
    assert loop_llm.invoke_count == 3
    assert result.policy_status == "ambiguous"


def test_policy_checker_node_delegates_with_only_order_id():
    # Arrange: state has order_id but order is None
    state = {
        "refund_id": "ref_node_order_id_only",
        "category": "damaged",
        "order": None,
        "order_id": "ORD-NODE-1",
    }
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Verified via external tools.",
    )
    mock_llm = make_mock_llm(expected_output)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.policy_checker.get_bedrock_llm", lambda: mock_llm)
        node_result = policy_checker_node(state)

    # Assert
    assert node_result["policy_status"] == "pass"


def test_check_policy_deterministic_pass_has_empty_tool_calls():
    """Verify deterministic pass returns tool_calls == [] in PolicyCheckerOutput."""
    order = {
        "order_id": "ORD-AUDIT-PASS",
        "order_amount": 100.0,
        "delivery_status": "delivered",
        "delivery_date": date.today().isoformat(),
    }
    result = check_policy(category="damaged", order=order)
    assert result.policy_status == "pass"
    assert result.tool_calls == []


def test_check_policy_invoking_carrier_tool_records_tool_calls_audit():
    """Verify policy check invoking query_carrier_tracking returns audit log in output.tool_calls."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
        "purchase_date": "2026-09-01",
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1005"},
            "id": "call_trk_audit_1",
        }],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Carrier tracking confirmed shipment is delayed.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    assert result.policy_status == "pass"
    assert len(result.tool_calls) == 1
    audit = result.tool_calls[0]
    assert audit["tool_name"] == "query_carrier_tracking"
    assert audit["tool_call_id"] == "call_trk_audit_1"
    assert audit["tool_input"] == {"tracking_number": "TRK-1005"}
    assert isinstance(audit["tool_output"], dict)
    assert audit["tool_output"]["found"] is True
    assert audit["tool_output"]["tracking_number"] == "TRK-1005"
    assert "timestamp" in audit


def test_check_policy_invoking_payment_tool_records_tool_calls_audit():
    """Verify policy check invoking query_payment_transaction returns audit log in output.tool_calls."""
    order = {
        "order_id": "ORD-1001",
        "order_amount": 250.0,
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_payment_transaction",
            "args": {"order_id": "ORD-1001"},
            "id": "call_pay_audit_1",
        }],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["charge_status_verified"],
        failed_rules=[],
        policy_reasoning="Payment charge verified as succeeded and eligible.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    result = check_policy(category="damaged", order=order, llm=mock_llm)

    assert len(result.tool_calls) == 1
    audit = result.tool_calls[0]
    assert audit["tool_name"] == "query_payment_transaction"
    assert audit["tool_call_id"] == "call_pay_audit_1"
    assert audit["tool_input"] == {"order_id": "ORD-1001"}
    assert isinstance(audit["tool_output"], dict)
    assert audit["tool_output"]["charge_status"] == "succeeded"
    assert audit["tool_output"]["refund_eligibility"] is True
    assert "timestamp" in audit


def test_check_policy_simulated_tool_exception_records_error_payload():
    """Verify simulated tool execution exception records error payload in output.tool_calls without crashing."""
    from langchain_core.tools import tool

    @tool("crashing_tool")
    def crashing_tool(tracking_number: str) -> str:
        """A crashing tool."""
        raise RuntimeError("Carrier service connection timeout")

    order = {
        "order_id": "ORD-1005",
        "order_amount": 100.0,
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "crashing_tool",
            "args": {"tracking_number": "TRK-CRASH"},
            "id": "call_crash_1",
        }],
    )
    expected_output = PolicyCheckerOutput(
        policy_status="ambiguous",
        passed_rules=[],
        failed_rules=[],
        policy_reasoning="Tool crashed; escalating to human operator.",
    )
    mock_llm = MockToolCallingLLM(responses=[tool_call_msg], final_output=expected_output)

    result = check_policy(category="late_delivery", order=order, llm=mock_llm, tools=[crashing_tool])

    assert isinstance(result, PolicyCheckerOutput)
    assert len(result.tool_calls) == 1
    audit = result.tool_calls[0]
    assert audit["tool_name"] == "crashing_tool"
    assert audit["tool_call_id"] == "call_crash_1"
    assert "error" in audit["tool_output"]
    assert "Tool execution error: Carrier service connection timeout" in audit["tool_output"]["error"]


def test_policy_checker_node_includes_tool_calls():
    """Verify policy_checker_node includes tool_calls in the returned state dictionary."""
    state = {
        "refund_id": "ref_node_tool_calls_test",
        "category": "damaged",
        "order": {
            "order_id": "ORD-NODE-TC",
            "order_amount": 100.0,
            "delivery_status": "delivered",
            "delivery_date": date.today().isoformat(),
        },
    }
    node_result = policy_checker_node(state)
    assert "tool_calls" in node_result
    assert isinstance(node_result["tool_calls"], list)
    assert node_result["tool_calls"] == []


