"""Unit tests for Policy Checker Agent and deterministic bypass behavior."""

from datetime import date
import json
from typing import Any
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
import pytest

from app.agents.policy_checker import FINAL_SYNTHESIS_PROMPT, check_policy, policy_checker_node
from app.schemas.policy_checker import PolicyCheckerOutput



def make_mock_llm(output: PolicyCheckerOutput) -> MagicMock:
    """Helper to create a mocked BaseChatModel returning a structured PolicyCheckerOutput."""
    mock = MagicMock()
    json_text = output.model_dump_json()
    ai_msg = AIMessage(content=f"```json\n{json_text}\n```")
    mock.invoke.return_value = ai_msg
    bound = MagicMock()
    bound.invoke.return_value = ai_msg
    mock.bind_tools.return_value = bound
    mock.with_structured_output.return_value = RunnableLambda(lambda _: output)
    mock.final_output = output
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
    mock_llm.invoke.assert_not_called()
    mock_llm.bind_tools.assert_not_called()


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
    mock_llm.invoke.assert_not_called()
    mock_llm.bind_tools.assert_not_called()


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

    # Verify LLM WAS called and with_structured_output was NOT called
    mock_llm.with_structured_output.assert_not_called()
    assert mock_llm.bind_tools.called or mock_llm.invoke.called


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
    mock_llm.with_structured_output.assert_not_called()
    assert mock_llm.bind_tools.called or mock_llm.invoke.called


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
        return AIMessage(content=f"```json\n{self.final_output.model_dump_json()}\n```", tool_calls=[])

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
            self.tool_loop_invocations = 0
            self.synthesis_invocations = 0

        def bind_tools(self, tools: list[Any]) -> "InfiniteLoopLLM":
            return self

        def invoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
            if any(
                isinstance(m, HumanMessage) and "Provide your final policy determination" in str(getattr(m, "content", ""))
                for m in messages
            ):
                self.synthesis_invocations += 1
                return AIMessage(content=f"```json\n{self.output.model_dump_json()}\n```")
            self.tool_loop_invocations += 1
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
    assert loop_llm.tool_loop_invocations == 3
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


def test_check_policy_extracts_json_enclosed_in_markdown_code_fences():
    """Verify structured output extraction when LLM returns JSON enclosed in markdown code fences."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    fenced_json = """Here is the policy evaluation:
```json
{
  "policy_status": "pass",
  "passed_rules": ["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
  "failed_rules": [],
  "policy_reasoning": "Carrier tracking verified shipment is delayed in transit past expected delivery date."
}
```
Evaluation complete."""

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content=fenced_json)
    bound_mock = MagicMock()
    bound_mock.invoke.return_value = AIMessage(content=fenced_json, tool_calls=[])
    mock_llm.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "pass"
    assert "refund_window_days" in result.passed_rules
    assert "delayed in transit" in result.policy_reasoning
    mock_llm.with_structured_output.assert_not_called()


def test_check_policy_extracts_raw_unfenced_json_with_surrounding_text():
    """Verify structured output extraction when LLM returns raw un-fenced JSON with surrounding text."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    unfenced_json = """Based on the policy rules and verified shipment status:
{
  "policy_status": "fail",
  "passed_rules": ["max_order_amount"],
  "failed_rules": ["refund_window_days"],
  "policy_reasoning": "Shipment arrived within standard transit window and is not eligible."
}
Please proceed accordingly."""

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content=unfenced_json)
    bound_mock = MagicMock()
    bound_mock.invoke.return_value = AIMessage(content=unfenced_json, tool_calls=[])
    mock_llm.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "fail"
    assert "refund_window_days" in result.failed_rules
    assert "not eligible" in result.policy_reasoning
    mock_llm.with_structured_output.assert_not_called()


def test_check_policy_does_not_pass_tool_choice_with_reasoning_config():
    """Verify structured output extraction does NOT pass toolChoice='tool' or 'any' when reasoningConfig is present."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
        "purchase_date": "2026-09-01",
    }

    invoked_kwargs_list: list[dict[str, Any]] = []

    mock_model = MagicMock()
    mock_model.additional_model_request_fields = {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "high"}
    }

    bound_mock = MagicMock()

    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1005"},
            "id": "call_trk_reasoning",
        }],
    )
    synthesis_msg = AIMessage(
        content=json.dumps({
            "policy_status": "pass",
            "passed_rules": ["refund_window_days"],
            "failed_rules": [],
            "policy_reasoning": "Tracking confirmed delay.",
        })
    )

    def mock_bound_invoke(messages: list[Any], **kwargs: Any) -> AIMessage:
        invoked_kwargs_list.append(kwargs)
        if len(invoked_kwargs_list) == 1:
            return tool_call_msg
        return synthesis_msg

    def mock_model_invoke(messages: list[Any], **kwargs: Any) -> AIMessage:
        invoked_kwargs_list.append(kwargs)
        return synthesis_msg

    bound_mock.invoke.side_effect = mock_bound_invoke
    mock_model.bind_tools.return_value = bound_mock
    mock_model.invoke.side_effect = mock_model_invoke

    result = check_policy(category="late_delivery", order=order, llm=mock_model)

    assert result.policy_status == "pass"
    mock_model.with_structured_output.assert_not_called()

    # Check that neither bind_tools nor invoke calls passed toolChoice='tool' or 'any'
    if mock_model.bind_tools.call_args:
        bind_kwargs = mock_model.bind_tools.call_args[1]
        assert bind_kwargs.get("tool_choice") not in ("tool", "any")
        assert bind_kwargs.get("toolChoice") not in ("tool", "any")

    for kw in invoked_kwargs_list:
        assert kw.get("tool_choice") not in ("tool", "any")
        assert kw.get("toolChoice") not in ("tool", "any")
        if isinstance(kw.get("tool_choice"), dict):
            assert "tool" not in kw["tool_choice"]


def test_check_policy_invalid_json_falls_back_to_ambiguous():
    """Verify graceful fallback to policy_status='ambiguous' when model returns invalid JSON."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    non_json_msg = AIMessage(
        content="I am unable to provide a structured policy determination due to unclear order facts."
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = non_json_msg
    bound_mock = MagicMock()
    bound_mock.invoke.return_value = non_json_msg
    mock_llm.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "ambiguous"
    assert "Could not parse policy determination" in result.policy_reasoning or "unclear" in result.policy_reasoning


def test_policy_checker_node_produces_expected_output_with_reasoning_extraction():
    """Verify policy_checker_node produces the expected output state dictionary from reasoning-compatible structured output."""
    state = {
        "refund_id": "ref_node_reasoning_test",
        "category": "late_delivery",
        "order": {
            "order_id": "ORD-1005",
            "order_amount": 200.0,
            "delivery_status": "in_transit",
        },
    }
    json_payload = json.dumps({
        "policy_status": "pass",
        "passed_rules": ["refund_window_days", "eligible_delivery_statuses"],
        "failed_rules": [],
        "policy_reasoning": "Reasoning safe extraction verified late delivery.",
    })
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.return_value = AIMessage(
        content=f"```json\n{json_payload}\n```", tool_calls=[]
    )
    mock_llm.bind_tools.return_value = bound_mock

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.policy_checker.get_bedrock_llm", lambda: mock_llm)
        node_result = policy_checker_node(state)

    assert node_result["policy_status"] == "pass"
    assert "refund_window_days" in node_result["passed_rules"]
    assert "Reasoning safe extraction" in node_result["policy_reasoning"]
    assert "tool_calls" in node_result


def test_check_policy_exception_on_late_delivery_returns_unmasked_reasoning():
    """Verify that an exception on late delivery returns unmasked error reasoning and does not mask with pass string."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = RuntimeError("Bedrock connection timeout")
    mock_llm.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "ambiguous"
    assert "External verification failed: Bedrock connection timeout" in result.policy_reasoning
    assert "All policy rules passed" not in result.policy_reasoning
    assert result.matched_policy_rule is not None
    assert result.tool_calls == []


def test_check_policy_exception_on_ambiguous_order_reports_error_details():
    """Verify that an exception on ambiguous deterministic findings reports external verification failure."""
    order = {
        "order_id": "ORD-AMB-1",
        "order_amount": 100.0,
    }
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = RuntimeError("Bedrock model unavailable")
    mock_llm.bind_tools.return_value = bound_mock

    result = check_policy(category="damaged", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "ambiguous"
    assert "External verification failed: Bedrock model unavailable" in result.policy_reasoning


def test_check_policy_exception_after_partial_tool_execution_preserves_tool_calls():
    """Verify that when an exception occurs after tool execution, tool_calls are preserved."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1005"},
            "id": "call_trk_err",
        }],
    )
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = [
        tool_call_msg,
        RuntimeError("Bedrock gateway timeout during tool response turn"),
    ]
    mock_llm.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "ambiguous"
    assert "External verification failed: Bedrock gateway timeout during tool response turn" in result.policy_reasoning
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == "query_carrier_tracking"


def test_check_policy_exception_with_empty_message_formats_exception_name():
    """Verify that an exception with an empty message formats as External verification failed: <ExceptionName>."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = Exception("")
    mock_llm.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "ambiguous"
    assert result.policy_reasoning == "External verification failed: Exception"


def test_policy_checker_node_propagates_unmasked_exception_reasoning():
    """Verify policy_checker_node produces output state with unmasked exception reasoning and preserved tool_calls."""
    state = {
        "refund_id": "ref_err_test",
        "category": "late_delivery",
        "order": {
            "order_id": "ORD-1005",
            "order_amount": 200.0,
            "delivery_status": "in_transit",
        },
    }
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = RuntimeError("Bedrock throttled")
    mock_llm.bind_tools.return_value = bound_mock

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agents.policy_checker.get_bedrock_llm", lambda: mock_llm)
        node_result = policy_checker_node(state)

    assert node_result["policy_status"] == "ambiguous"
    assert "External verification failed: Bedrock throttled" in node_result["policy_reasoning"]
    assert "tool_calls" in node_result


def test_downstream_decision_node_escalates_on_policy_verification_failure():
    """Verify downstream decision_node evaluates ambiguous verification failure state to escalate."""
    from app.agents.decision import decision_node

    state = {
        "category": "late_delivery",
        "classification_confidence": 0.95,
        "policy_status": "ambiguous",
        "policy_reasoning": "External verification failed: Bedrock connection timeout",
        "matched_policy_rule": {"refund_window_days": 30},
        "failed_rules": [],
        "tool_calls": [],
    }

    decision_state = decision_node(state)

    assert decision_state["decision"] == "escalate"
    assert decision_state["status"] == "escalated"
    assert "External verification failed" in decision_state["reasoning"]


def test_check_policy_ord_1010_dual_tool_verification():
    """Verify that policy evaluation for ORD-1010 executes both carrier and payment tools, recording both in tool_calls."""
    order = {
        "order_id": "ORD-1010",
        "item": "Professional Mirrorless Camera",
        "order_amount": 450.0,
        "delivery_status": "delivered",
        "purchase_date": "2026-09-15",
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "query_carrier_tracking",
                "args": {"tracking_number": "TRK-1010"},
                "id": "call_trk_1010",
            },
            {
                "name": "query_payment_transaction",
                "args": {"order_id": "ORD-1010"},
                "id": "call_pay_1010",
            },
        ],
    )
    synthesis_msg = AIMessage(
        content=json.dumps({
            "policy_status": "pass",
            "passed_rules": ["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
            "failed_rules": [],
            "policy_reasoning": "Carrier delivery confirmed and payment transaction is eligible for refund.",
        })
    )
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = [tool_call_msg, synthesis_msg]
    mock_llm.bind_tools.return_value = bound_mock
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "pass"
    assert len(result.tool_calls) == 2
    tool_names = {t["tool_name"] for t in result.tool_calls}
    assert tool_names == {"query_carrier_tracking", "query_payment_transaction"}

    carrier_call = next(t for t in result.tool_calls if t["tool_name"] == "query_carrier_tracking")
    assert carrier_call["tool_output"]["found"] is True
    assert carrier_call["tool_output"]["carrier"] == "FedEx"
    assert carrier_call["tool_output"]["proof_of_delivery_photo_available"] is True

    payment_call = next(t for t in result.tool_calls if t["tool_name"] == "query_payment_transaction")
    assert payment_call["tool_output"]["found"] is True
    assert payment_call["tool_output"]["charge_amount"] == 450.0
    assert payment_call["tool_output"]["refund_eligibility"] is True


def test_check_policy_ord_1010_payment_dispute_evaluates_to_ambiguous():
    """Verify that if carrier succeeds but payment reveals dispute, both tool calls are preserved and status is ambiguous."""
    order = {
        "order_id": "ORD-1010",
        "item": "Professional Mirrorless Camera",
        "order_amount": 450.0,
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "query_carrier_tracking",
                "args": {"tracking_number": "TRK-1010"},
                "id": "call_trk_1010_disp",
            },
            {
                "name": "query_payment_transaction",
                "args": {"order_id": "ORD-1006"},  # disputed order in payment registry
                "id": "call_pay_1010_disp",
            },
        ],
    )
    synthesis_msg = AIMessage(
        content=json.dumps({
            "policy_status": "ambiguous",
            "passed_rules": ["eligible_delivery_statuses"],
            "failed_rules": [],
            "policy_reasoning": "Carrier delivery confirmed but Stripe charge dispute is currently under review.",
        })
    )
    mock_llm = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = [tool_call_msg, synthesis_msg]
    mock_llm.bind_tools.return_value = bound_mock
    result = check_policy(category="damaged", order=order, llm=mock_llm)

    assert isinstance(result, PolicyCheckerOutput)
    assert result.policy_status == "ambiguous"
    assert len(result.tool_calls) == 2
    tool_names = {t["tool_name"] for t in result.tool_calls}
    assert tool_names == {"query_carrier_tracking", "query_payment_transaction"}

    payment_call = next(t for t in result.tool_calls if t["tool_name"] == "query_payment_transaction")
    assert payment_call["tool_output"]["dispute_status"] == "under_review"
    assert payment_call["tool_output"]["refund_eligibility"] is False
    assert "dispute" in result.policy_reasoning.lower()


def test_check_policy_synthesis_calls_bound_model_invoke_not_unbound_model():
    """AC 1800: Verify that bound_model.invoke is called for synthesis and unbound model.invoke is not called."""
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
            "id": "call_trk_bound_test",
        }],
    )
    synthesis_msg = AIMessage(
        content=json.dumps({
            "policy_status": "pass",
            "passed_rules": ["refund_window_days", "eligible_delivery_statuses"],
            "failed_rules": [],
            "policy_reasoning": "Tracking confirms in transit delay past window.",
        })
    )
    mock_model = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = [tool_call_msg, synthesis_msg]
    mock_model.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_model)

    assert result.policy_status == "pass"
    # Verify bound_model.invoke was called for both tool calling and synthesis
    assert bound_mock.invoke.call_count == 2
    # Verify unbound model.invoke was never called directly for synthesis
    mock_model.invoke.assert_not_called()


def test_check_policy_no_toolconfig_runtime_warning_emitted():
    """AC 1801: Verify that no RuntimeWarning matching 'Tool messages were passed without toolConfig' is emitted."""
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
            "id": "call_trk_warn_test",
        }],
    )
    synthesis_msg = AIMessage(
        content=json.dumps({
            "policy_status": "pass",
            "passed_rules": ["refund_window_days"],
            "failed_rules": [],
            "policy_reasoning": "Carrier delay confirmed without warnings.",
        })
    )

    class MockConverseWarningModel:
        """Mock LLM that warns if ToolMessage is passed to an unbound instance."""
        def __init__(self, is_bound: bool = False):
            self.is_bound = is_bound
            self.call_count = 0

        def bind_tools(self, tools: list[Any]) -> "MockConverseWarningModel":
            return MockConverseWarningModel(is_bound=True)

        def invoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
            self.call_count += 1
            has_tool_message = any(isinstance(m, ToolMessage) for m in messages)
            if has_tool_message and not self.is_bound:
                import warnings
                warnings.warn(
                    "Tool messages were passed without toolConfig, converting to text format",
                    RuntimeWarning,
                )
            if self.call_count == 1:
                return tool_call_msg
            return synthesis_msg

    model = MockConverseWarningModel(is_bound=False)

    import warnings
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        result = check_policy(category="late_delivery", order=order, llm=model)

    assert result.policy_status == "pass"
    tool_warnings = [
        w for w in recorded_warnings
        if issubclass(w.category, RuntimeWarning)
        and "Tool messages were passed without toolConfig" in str(w.message)
    ]
    assert len(tool_warnings) == 0, f"Expected 0 toolConfig warnings, got: {tool_warnings}"


def test_check_policy_synthesis_does_not_inject_tool_choice_with_reasoning_config():
    """AC 1802: Verify that bound_model.invoke during synthesis does NOT inject toolChoice='tool' or 'any'."""
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
            "id": "call_trk_rc_test",
        }],
    )
    synthesis_msg = AIMessage(
        content=json.dumps({
            "policy_status": "pass",
            "passed_rules": ["refund_window_days"],
            "failed_rules": [],
            "policy_reasoning": "Reasoning config compliant synthesis.",
        })
    )
    mock_model = MagicMock()
    mock_model.additional_model_request_fields = {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "high"}
    }
    bound_mock = MagicMock()
    invoked_kwargs_list: list[dict[str, Any]] = []

    def mock_invoke(messages: list[Any], **kwargs: Any) -> AIMessage:
        invoked_kwargs_list.append(kwargs)
        if len(invoked_kwargs_list) == 1:
            return tool_call_msg
        return synthesis_msg

    bound_mock.invoke.side_effect = mock_invoke
    mock_model.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_model)

    assert result.policy_status == "pass"
    assert bound_mock.invoke.call_count == 2
    for kw in invoked_kwargs_list:
        assert kw.get("tool_choice") not in ("tool", "any")
        assert kw.get("toolChoice") not in ("tool", "any")
        if isinstance(kw.get("tool_choice"), dict):
            assert "tool" not in kw["tool_choice"]


def test_check_policy_synthesis_structured_output_from_bound_model_direct_and_fenced():
    """AC 1803: Verify check_policy extracts valid PolicyCheckerOutput if bound_model returns PolicyCheckerOutput directly or fenced JSON."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    # 1. Direct PolicyCheckerOutput from bound_model.invoke
    direct_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days"],
        failed_rules=[],
        policy_reasoning="Direct structured output from bound model.",
    )
    mock_model_1 = MagicMock()
    bound_mock_1 = MagicMock()
    bound_mock_1.invoke.side_effect = [
        AIMessage(content="Evaluating..."),
        direct_output,
    ]
    mock_model_1.bind_tools.return_value = bound_mock_1

    result_1 = check_policy(category="late_delivery", order=order, llm=mock_model_1)
    assert result_1.policy_status == "pass"
    assert result_1.policy_reasoning == "Direct structured output from bound model."

    # 2. Markdown fenced JSON from bound_model.invoke
    fenced_content = "```json\n" + json.dumps({
        "policy_status": "fail",
        "passed_rules": [],
        "failed_rules": ["refund_window_days"],
        "policy_reasoning": "Fenced JSON from bound model synthesis.",
    }) + "\n```"
    mock_model_2 = MagicMock()
    bound_mock_2 = MagicMock()
    bound_mock_2.invoke.side_effect = [
        AIMessage(content="Evaluating..."),
        AIMessage(content=fenced_content),
    ]
    mock_model_2.bind_tools.return_value = bound_mock_2

    result_2 = check_policy(category="late_delivery", order=order, llm=mock_model_2)
    assert result_2.policy_status == "fail"
    assert result_2.policy_reasoning == "Fenced JSON from bound model synthesis."


def test_check_policy_synthesis_exception_handled_gracefully():
    """AC 1804: Verify exception during bound_model synthesis is caught, preserving tool_calls and reporting ambiguous."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "query_carrier_tracking",
            "args": {"tracking_number": "TRK-1005"},
            "id": "call_trk_synth_fail",
        }],
    )
    mock_model = MagicMock()
    bound_mock = MagicMock()
    bound_mock.invoke.side_effect = [
        tool_call_msg,
        RuntimeError("Bedrock service unavailable during synthesis"),
    ]
    mock_model.bind_tools.return_value = bound_mock

    result = check_policy(category="late_delivery", order=order, llm=mock_model)

    assert result.policy_status == "ambiguous"
    assert "External verification failed: Bedrock service unavailable during synthesis" in result.policy_reasoning
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == "query_carrier_tracking"


def test_check_policy_fallback_when_model_lacks_bind_tools():
    """AC 1799: Verify clean fallback to model when model does not implement bind_tools or active_tools is empty."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    synthesis_msg = AIMessage(
        content=json.dumps({
            "policy_status": "pass",
            "passed_rules": ["refund_window_days"],
            "failed_rules": [],
            "policy_reasoning": "Fallback model without bind_tools succeeded.",
        })
    )

    class ModelWithoutBindTools:
        """Model without bind_tools method."""
        def invoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
            return synthesis_msg

    model = ModelWithoutBindTools()
    assert not hasattr(model, "bind_tools")

    result = check_policy(category="late_delivery", order=order, llm=model)
    assert result.policy_status == "pass"
    assert "Fallback model without bind_tools succeeded" in result.policy_reasoning


def test_check_policy_fallback_final_output_inspection_on_bound_and_unbound_model():
    """AC 1798: Verify fallback attribute inspection checks both bound_model and model for final_output."""
    order = {
        "order_id": "ORD-1005",
        "order_amount": 200.0,
        "delivery_status": "in_transit",
    }
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days"],
        failed_rules=[],
        policy_reasoning="Extracted from mock final_output attribute.",
    )

    # 1. final_output attribute on bound_model
    mock_model_1 = MagicMock(spec=["bind_tools"])
    bound_mock_1 = MagicMock()
    bound_mock_1.final_output = expected_output
    bound_mock_1.invoke.return_value = AIMessage(content="Non-JSON raw text determination.")
    mock_model_1.bind_tools.return_value = bound_mock_1

    result_1 = check_policy(category="late_delivery", order=order, llm=mock_model_1)
    assert result_1.policy_status == "pass"
    assert result_1.policy_reasoning == "Extracted from mock final_output attribute."

    # 2. final_output attribute on model (unbound)
    mock_model_2 = MagicMock()
    mock_model_2.final_output = expected_output
    bound_mock_2 = MagicMock(spec=["invoke"])  # no final_output on bound_mock
    bound_mock_2.invoke.return_value = AIMessage(content="Non-JSON raw text determination.")
    mock_model_2.bind_tools.return_value = bound_mock_2

    result_2 = check_policy(category="late_delivery", order=order, llm=mock_model_2)
    assert result_2.policy_status == "pass"
    assert result_2.policy_reasoning == "Extracted from mock final_output attribute."




