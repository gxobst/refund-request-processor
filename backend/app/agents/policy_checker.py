"""Policy Checker Agent module integrating deterministic evaluation with LLM ambiguity analysis and autonomous tool calling."""

from datetime import datetime, timezone
import json
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
- query_carrier_tracking: Use this tool to look up carrier delivery status, delivery dates, and proof-of-delivery photos (useful for late delivery claims or lost packages).
- query_payment_transaction: Use this tool to look up Stripe charge status, dispute state, and refund eligibility for an order.

When evaluating requests requiring external verification (such as late deliveries or missing order data) or resolving ambiguities, call the appropriate tools to gather evidence before making a final determination.

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
    if eval_result.status == "pass" and category != "late_delivery":
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
                break

        # Produce final structured output
        structured_model = model.with_structured_output(PolicyCheckerOutput)
        raw_output = structured_model.invoke(messages)
        if isinstance(raw_output, dict):
            result = PolicyCheckerOutput.model_validate(raw_output)
        elif isinstance(raw_output, PolicyCheckerOutput):
            result = raw_output
        else:
            result = PolicyCheckerOutput.model_validate(raw_output)

        result.tool_calls = executed_tool_calls

    except Exception as e:
        return PolicyCheckerOutput(
            policy_status="ambiguous",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=eval_result.details or f"External verification failed: {str(e)}",
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

