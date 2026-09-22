"""Policy Checker Agent module integrating deterministic evaluation with LLM ambiguity analysis."""

from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.agents.llm import get_bedrock_llm
from app.policy.engine import evaluate_policy
from app.policy.loader import load_policies
from app.policy.schema import PolicyConfig
from app.schemas.policy_checker import PolicyCheckerOutput

AMBIGUITY_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are an expert refund policy analyst for an e-commerce platform.
A deterministic policy check returned an ambiguous condition (e.g. missing order attributes, unparseable dates, or contradictory conditions).
Evaluate the refund request category, order details, deterministic findings, and policy rules.
Determine if the ambiguity can be safely resolved, or if human escalation is required.

Return a structured output with:
- policy_status: 'pass' (eligible), 'fail' (clearly ineligible), or 'ambiguous' (requires human review).
- passed_rules: list of satisfied rule names.
- failed_rules: list of failed rule names.
- policy_reasoning: explanation of your determination and justification for escalation if ambiguous.
""",
    ),
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
) -> PolicyCheckerOutput:
    """Evaluate a refund request against policies, bypassing LLM on clear-cut cases.

    Args:
        category: Refund category.
        order: Order data dictionary.
        policies: Optional loaded PolicyConfig. Defaults to default policies.json.
        llm: Optional BaseChatModel instance for ambiguity resolution.

    Returns:
        PolicyCheckerOutput instance.
    """
    active_policies = policies if policies is not None else load_policies()
    eval_result = evaluate_policy(category=category, order=order, policy=active_policies)

    # 1. Deterministic Pass Bypass
    if eval_result.status == "pass":
        return PolicyCheckerOutput(
            policy_status="pass",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=eval_result.details or "All policy rules passed.",
        )

    # 2. Deterministic Fail Bypass
    if eval_result.status == "fail":
        return PolicyCheckerOutput(
            policy_status="fail",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=eval_result.details or f"Evaluation failed for rules: {', '.join(eval_result.failed_rules)}",
        )

    # 3. LLM Ambiguity Analysis
    model = llm or get_bedrock_llm()
    structured_llm = model.with_structured_output(PolicyCheckerOutput)
    chain = AMBIGUITY_PROMPT | structured_llm

    rule_repr = (
        eval_result.matched_policy_rule.model_dump()
        if hasattr(eval_result.matched_policy_rule, "model_dump")
        else eval_result.matched_policy_rule
    )

    llm_output = chain.invoke({
        "category": category,
        "order": str(order),
        "details": str(eval_result.details),
        "policy_rule": str(rule_repr),
    })

    if isinstance(llm_output, dict):
        result = PolicyCheckerOutput.model_validate(llm_output)
    else:
        result = llm_output

    if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
        result.matched_policy_rule = eval_result.matched_policy_rule

    return result


def policy_checker_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node function executing the Policy Checker Agent.

    Args:
        state: Workflow state dictionary containing 'category' and 'order'.

    Returns:
        Updated dictionary containing policy checker keys.
    """
    category = state.get("category", "")
    order = state.get("order", {})
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
    }
