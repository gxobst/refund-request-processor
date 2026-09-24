"""Policy Checker Agent module integrating deterministic evaluation with LLM ambiguity analysis and autonomous tool calling."""

from datetime import datetime, timezone
import json
import re
from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate

from app.agents.llm import get_bedrock_llm
from app.policy.engine import evaluate_policy
from app.policy.loader import load_policies
from app.policy.schema import PolicyConfig
from app.schemas.policy_checker import PolicyCheckerOutput
from app.tools import ALL_TOOLS, query_carrier_tracking, query_payment_transaction

POLICY_CHECKER_SYSTEM_PROMPT = """You are an expert refund policy analyst for an e-commerce platform.
Evaluate the refund request category, order details, deterministic findings, and policy rules to determine refund eligibility.

You have access to the following verification tools:
- query_carrier_tracking: Use this tool to look up carrier delivery status, delivery dates, and proof-of-delivery photos (useful for late delivery claims or lost packages). If a tracking number is not explicitly given in the order details, use 'TRK-' followed by the order ID number (for example, 'TRK-1005' for order 'ORD-1005').
- query_payment_transaction: Use this tool to look up Stripe charge status, dispute state, and refund eligibility for an order.

When evaluating requests requiring external verification (such as late deliveries, missing order data, high-value orders, or ambiguous claims), call the appropriate tools to gather evidence before making a final determination. For high-value orders or ambiguous claims, verify both carrier delivery status (via query_carrier_tracking) and payment transaction status (via query_payment_transaction) to ensure delivery proof and charge eligibility before concluding.

Return a structured output with:
- policy_status: 'pass' (eligible), 'fail' (clearly ineligible), or 'ambiguous' (requires human review).
- passed_rules: list of satisfied rule names.
- failed_rules: list of failed rule names.
- policy_reasoning: explanation of your determination and justification for escalation if ambiguous.
"""

AMBIGUITY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", POLICY_CHECKER_SYSTEM_PROMPT),
    (
        "human",
        """Category: {category}
Order Details: {order}
Deterministic Findings: {details}
Policy Rule: {policy_rule}

Analyze the situation and provide your determination:""",
    ),
])


FINAL_SYNTHESIS_PROMPT = """Provide your final policy determination formatted as a strict JSON object with keys:
- "policy_status": "pass", "fail", or "ambiguous"
- "passed_rules": list of passed rule names (e.g. ["refund_window_days", "eligible_delivery_statuses", "max_order_amount"])
- "failed_rules": list of failed rule names
- "policy_reasoning": detailed explanation of your determination and evidence

Respond with ONLY the JSON object, with no additional conversational text or markdown code fences."""


def _extract_text(content: Any) -> str:
    """Extract plain text from model message content (handling str or block lists)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    text_parts.append(block["text"])
                elif "text" in block and block.get("type") != "reasoning_content":
                    text_parts.append(block["text"])
        return "\n".join(text_parts)
    return str(content) if content is not None else ""


def _parse_policy_checker_output(
    text: str,
    eval_result: Any,
    executed_tool_calls: list[dict[str, Any]],
) -> PolicyCheckerOutput | None:
    """Attempt to extract and parse PolicyCheckerOutput from text containing JSON."""
    if not text or not text.strip():
        return None

    candidate_strings: list[str] = []

    # 1. Search for JSON within markdown code blocks (```json ... ``` or ``` ... ```)
    code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if code_block_match:
        block_text = code_block_match.group(1).strip()
        candidate_strings.append(block_text)
        start = block_text.find("{")
        end = block_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate_strings.append(block_text[start : end + 1])

    regex_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if regex_match:
        candidate_strings.append(regex_match.group(1).strip())

    # 2. Check for first { and last } across entire text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate_strings.append(text[start : end + 1])

    # 3. Check trimmed full text
    candidate_strings.append(text.strip())

    for candidate in candidate_strings:
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                continue
            if "policy_status" not in parsed:
                continue

            if "matched_policy_rule" not in parsed or parsed["matched_policy_rule"] is None:
                parsed["matched_policy_rule"] = eval_result.matched_policy_rule

            if "tool_calls" not in parsed or not parsed["tool_calls"]:
                parsed["tool_calls"] = executed_tool_calls

            output = PolicyCheckerOutput.model_validate(parsed)
            if output.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                output.matched_policy_rule = eval_result.matched_policy_rule
            if not output.tool_calls and executed_tool_calls:
                output.tool_calls = executed_tool_calls
            return output
        except Exception:
            continue

    return None


def check_policy(
    category: str,
    order: dict[str, Any],
    policies: PolicyConfig | None = None,
    llm: BaseChatModel | None = None,
    tools: list[Any] | None = None,
    max_tool_iterations: int = 5,
) -> PolicyCheckerOutput:
    """Evaluate a refund request against policies, bypassing LLM on clear-cut cases.

    Args:
        category: Refund category.
        order: Order data dictionary.
        policies: Optional loaded PolicyConfig. Defaults to default policies.json.
        llm: Optional BaseChatModel instance for ambiguity resolution and tool calling.
        tools: Optional list of tools to bind to the model. Defaults to carrier and payment tools.
        max_tool_iterations: Maximum number of tool calling turns (default 5).

    Returns:
        PolicyCheckerOutput instance.
    """
    active_policies = policies if policies is not None else load_policies()
    eval_result = evaluate_policy(category=category, order=order, policy=active_policies)

    # 1. Deterministic Pass Bypass
    # Clear-cut pass bypasses LLM except for late_delivery which requires external carrier verification
    # or high-value orders (order_amount >= 400.0) which require dual external verification
    is_high_value = float(order.get("order_amount", 0.0) or 0.0) >= 400.0
    if eval_result.status == "pass" and category != "late_delivery" and not is_high_value:
        return PolicyCheckerOutput(
            policy_status="pass",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=eval_result.details or "All policy rules passed.",
            tool_calls=[],
        )

    # 2. Deterministic Fail Bypass
    # Clear-cut fail on hard constraints (e.g. max_order_amount exceeded or non-late_delivery expired window)
    if eval_result.status == "fail":
        is_hard_constraint = (
            "max_order_amount" in eval_result.failed_rules
            or category != "late_delivery"
        )
        if is_hard_constraint:
            return PolicyCheckerOutput(
                policy_status="fail",
                matched_policy_rule=eval_result.matched_policy_rule,
                passed_rules=eval_result.passed_rules,
                failed_rules=eval_result.failed_rules,
                policy_reasoning=eval_result.details
                or f"Evaluation failed for rules: {', '.join(eval_result.failed_rules)}",
                tool_calls=[],
            )

    # 3. LLM External Verification and Ambiguity Resolution
    executed_tool_calls: list[dict[str, Any]] = []
    active_tools = tools if tools is not None else [query_carrier_tracking, query_payment_transaction]
    tool_map: dict[str, Any] = {}
    for t in active_tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            tool_map[name] = t

    model = llm or get_bedrock_llm()
    if active_tools and hasattr(model, "bind_tools"):
        bound_model = model.bind_tools(active_tools)
    else:
        bound_model = model

    rule_repr = (
        eval_result.matched_policy_rule.model_dump()
        if hasattr(eval_result.matched_policy_rule, "model_dump")
        else eval_result.matched_policy_rule
    )

    human_content = f"""Category: {category}
Order Details: {order}
Deterministic Findings: {eval_result.details}
Policy Rule: {rule_repr}

Analyze the situation and provide your determination:"""

    messages: list[Any] = [
        SystemMessage(content=POLICY_CHECKER_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]

    try:
        # Multi-turn tool execution loop
        for _ in range(max_tool_iterations):
            response = bound_model.invoke(messages)
            if isinstance(response, PolicyCheckerOutput):
                result = response
                if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                    result.matched_policy_rule = eval_result.matched_policy_rule
                result.tool_calls = executed_tool_calls
                return result

            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None)
            if isinstance(tool_calls, list) and tool_calls:
                for call in tool_calls:
                    name = call.get("name", "")
                    raw_args = call.get("args", {})
                    call_id = call.get("id") or "call_id"

                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            args = raw_args
                    else:
                        args = raw_args

                    if name in tool_map:
                        try:
                            tool = tool_map[name]
                            if hasattr(tool, "invoke"):
                                raw_res = tool.invoke(args)
                            elif isinstance(args, dict):
                                raw_res = tool(**args)
                            else:
                                raw_res = tool(args)
                            content = raw_res if isinstance(raw_res, str) else json.dumps(raw_res)
                            tool_output = raw_res
                        except Exception as e:
                            tool_output = {"error": f"Tool execution error: {str(e)}"}
                            content = json.dumps(tool_output)
                    else:
                        tool_output = {
                            "error": f"Tool '{name}' not found. Available tools: {list(tool_map.keys())}"
                        }
                        content = json.dumps(tool_output)

                    audit_entry = {
                        "tool_name": name,
                        "tool_call_id": call_id,
                        "tool_input": args,
                        "tool_output": tool_output,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    executed_tool_calls.append(audit_entry)

                    messages.append(
                        ToolMessage(
                            content=content,
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
            else:
                # Fast extraction if terminal response already contains valid JSON
                fast_text = _extract_text(getattr(response, "content", ""))
                fast_result = _parse_policy_checker_output(
                    fast_text, eval_result, executed_tool_calls
                )
                if fast_result is not None:
                    return fast_result
                break

        # Produce final structured output via reasoning-safe extraction
        messages.append(HumanMessage(content=FINAL_SYNTHESIS_PROMPT))
        final_response = model.invoke(messages)

        if isinstance(final_response, PolicyCheckerOutput):
            result = final_response
            if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                result.matched_policy_rule = eval_result.matched_policy_rule
            result.tool_calls = executed_tool_calls
            return result

        final_text = _extract_text(getattr(final_response, "content", final_response))
        parsed_result = _parse_policy_checker_output(
            final_text, eval_result, executed_tool_calls
        )

        if parsed_result is not None:
            result = parsed_result
        elif hasattr(model, "final_output") and isinstance(getattr(model, "final_output"), PolicyCheckerOutput):
            result = getattr(model, "final_output").model_copy(deep=True)
            if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                result.matched_policy_rule = eval_result.matched_policy_rule
            result.tool_calls = executed_tool_calls
            return result
        else:
            return PolicyCheckerOutput(
                policy_status="ambiguous",
                matched_policy_rule=eval_result.matched_policy_rule,
                passed_rules=eval_result.passed_rules,
                failed_rules=eval_result.failed_rules,
                policy_reasoning=f"Could not parse policy determination from model output: {final_text[:200]}",
                tool_calls=executed_tool_calls,
            )

    except Exception as e:
        err_msg = str(e).strip()
        error_detail = err_msg if err_msg else type(e).__name__
        return PolicyCheckerOutput(
            policy_status="ambiguous",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=f"External verification failed: {error_detail}",
            tool_calls=executed_tool_calls,
        )

    if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
        result.matched_policy_rule = eval_result.matched_policy_rule

    if not result.tool_calls and executed_tool_calls:
        result.tool_calls = executed_tool_calls

    return result


def policy_checker_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node function executing the Policy Checker Agent.

    Args:
        state: Workflow state dictionary containing 'category', 'order', and/or 'order_id'.

    Returns:
        Updated dictionary containing policy checker keys.
    """
    category = state.get("category", "")
    order = state.get("order")
    if not order:
        order = {"order_id": state.get("order_id", "")}

    output = check_policy(category=category, order=order)

    matched_rule = output.matched_policy_rule
    if hasattr(matched_rule, "model_dump"):
        matched_rule = matched_rule.model_dump()

    return {
        "policy_status": output.policy_status,
        "matched_policy_rule": matched_rule,
        "policy_reasoning": output.policy_reasoning,
        "passed_rules": output.passed_rules,
        "failed_rules": output.failed_rules,
        "tool_calls": output.tool_calls,
    }

