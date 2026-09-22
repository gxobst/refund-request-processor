"""Decision Agent module synthesizing classification and policy checks into a final refund decision."""

from typing import Any
from langchain_core.language_models import BaseChatModel

from app.schemas.decision import DecisionOutput


def make_decision(
    category: str,
    classification_confidence: float,
    policy_status: str,
    matched_policy_rule: dict[str, Any] | None,
    failed_rules: list[str],
    policy_reasoning: str,
    is_low_confidence: bool = False,
    missing_order_data: bool = False,
    policy_conflict: bool = False,
    llm: BaseChatModel | None = None,
) -> DecisionOutput:
    """Synthesize refund classification and policy evaluation into a final decision.

    Escalation triggers (per plan.md Section 5):
    1. Low classifier confidence: is_low_confidence is True or confidence < 0.7
    2. Ambiguous policy condition: policy_status == "ambiguous"
    3. Missing required order data: missing_order_data is True
    4. Policy rule conflict: policy_conflict is True

    Otherwise:
    - policy_status == "pass" -> auto_approve
    - policy_status == "fail" -> deny

    Args:
        category: Classified refund reason category.
        classification_confidence: Classifier confidence score (0.0 to 1.0).
        policy_status: Evaluated policy status ('pass', 'fail', 'ambiguous').
        matched_policy_rule: Applicable policy rule dictionary or None.
        failed_rules: List of failed rule names.
        policy_reasoning: Explanation from policy checker.
        is_low_confidence: Explicit low-confidence indicator flag.
        missing_order_data: Flag indicating missing order attributes.
        policy_conflict: Flag indicating contradictory policy rules.
        llm: Optional BaseChatModel instance (reserved for advanced synthesis).

    Returns:
        DecisionOutput with decision ('auto_approve', 'deny', 'escalate'), reasoning,
        matched_policy_rule, and confidence_score.
    """
    # 1. Escalation Trigger: Low Classifier Confidence
    if is_low_confidence or classification_confidence < 0.7:
        return DecisionOutput(
            decision="escalate",
            reasoning=f"Escalated to human review due to low classifier confidence ({classification_confidence:.2f} < 0.70).",
            matched_policy_rule=matched_policy_rule,
            confidence_score=classification_confidence,
        )

    # 2. Escalation Trigger: Missing Order Data
    if missing_order_data:
        return DecisionOutput(
            decision="escalate",
            reasoning="Escalated to human review due to missing required order data.",
            matched_policy_rule=matched_policy_rule,
            confidence_score=classification_confidence,
        )

    # 3. Escalation Trigger: Policy Rule Conflict
    if policy_conflict:
        return DecisionOutput(
            decision="escalate",
            reasoning="Escalated to human review due to contradictory policy rules.",
            matched_policy_rule=matched_policy_rule,
            confidence_score=classification_confidence,
        )

    # 4. Escalation Trigger: Ambiguous Policy Check
    if policy_status == "ambiguous":
        reason = policy_reasoning or "Unresolved policy ambiguity requires operator review."
        return DecisionOutput(
            decision="escalate",
            reasoning=f"Escalated to human review due to policy ambiguity: {reason}",
            matched_policy_rule=matched_policy_rule,
            confidence_score=classification_confidence,
        )

    # 5. Deterministic Auto-Approval
    if policy_status == "pass":
        return DecisionOutput(
            decision="auto_approve",
            reasoning=f"Refund automatically approved. Category '{category}' satisfied all policy rules ({policy_reasoning}).",
            matched_policy_rule=matched_policy_rule,
            confidence_score=classification_confidence,
        )

    # 6. Deterministic Denial
    if policy_status == "fail":
        failed_info = f"Failed rules: {', '.join(failed_rules)}." if failed_rules else policy_reasoning
        return DecisionOutput(
            decision="deny",
            reasoning=f"Refund request denied. {failed_info}",
            matched_policy_rule=matched_policy_rule,
            confidence_score=classification_confidence,
        )

    # Fallback for unexpected status
    return DecisionOutput(
        decision="escalate",
        reasoning=f"Escalated to human review due to unexpected policy status: '{policy_status}'.",
        matched_policy_rule=matched_policy_rule,
        confidence_score=classification_confidence,
    )


def decision_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node function executing the Decision Agent.

    Args:
        state: Workflow state dictionary containing classification and policy evaluations.

    Returns:
        Updated dictionary containing final decision keys and status.
    """
    category = state.get("category", "")
    confidence = state.get("classification_confidence", state.get("confidence_score", 0.0))
    is_low_conf = state.get("is_low_confidence", confidence < 0.7)
    policy_status = state.get("policy_status", "ambiguous")
    matched_rule = state.get("matched_policy_rule")
    failed_rules = state.get("failed_rules", [])
    policy_reasoning = state.get("policy_reasoning", "")
    missing_data = state.get("missing_order_data", False)
    rule_conflict = state.get("policy_conflict", False)

    output = make_decision(
        category=category,
        classification_confidence=confidence,
        policy_status=policy_status,
        matched_policy_rule=matched_rule,
        failed_rules=failed_rules,
        policy_reasoning=policy_reasoning,
        is_low_confidence=is_low_conf,
        missing_order_data=missing_data,
        policy_conflict=rule_conflict,
    )

    final_status = "escalated" if output.decision == "escalate" else "completed"

    return {
        "decision": output.decision,
        "reasoning": output.reasoning,
        "matched_policy_rule": output.matched_policy_rule,
        "confidence_score": output.confidence_score,
        "status": final_status,
    }
