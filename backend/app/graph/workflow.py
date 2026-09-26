"""LangGraph workflow assembly for refund request processing."""

from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes import (
    clarification_node,
    classifier_node,
    decision_node,
    intake_validate_node,
    policy_checker_node,
    save_dynamo_node,
)
from app.graph.state import RefundWorkflowState


def route_classifier(state: RefundWorkflowState) -> str:
    """Conditional router following classification.

    When classifier confidence is low (is_low_confidence is True, confidence_score < 0.70,
    or classification_confidence < 0.70):
    - Returns 'clarification' if clarification_count < 2.
    - Returns 'decision' if clarification_count >= 2 (escalating directly to human review).
    When classifier confidence is high (>= 0.70 and is_low_confidence is False):
    - Returns 'policy_checker' regardless of clarification_count.
    """
    conf = state.get("confidence_score")
    class_conf = state.get("classification_confidence")
    is_low_flag = state.get("is_low_confidence")

    is_low = (
        is_low_flag is True
        or (conf is not None and conf < 0.70)
        or (class_conf is not None and class_conf < 0.70)
    )

    if is_low:
        count = state.get("clarification_count")
        if count is None:
            count = 0
        if count < 2:
            return "clarification"
        return "decision"

    return "policy_checker"


def route_policy_check(state: RefundWorkflowState) -> str:
    """Conditional router following policy checking.

    - When missing_order_data is True, returns 'decision'.
    - When a product mismatch is detected ("product_mismatch" in failed_rules or is_product_mismatch):
      Returns 'clarification' if clarification_count < 2, else 'decision'.
    - When category == "damaged" and policy_status == "ambiguous" with
      "physical_damage_verification" in failed_rules:
      Returns 'clarification' if clarification_count < 2, else 'decision'.
    - Otherwise returns 'decision'.
    """
    if state.get("missing_order_data"):
        return "decision"

    category = state.get("category")
    policy_status = state.get("policy_status")
    failed_rules = state.get("failed_rules") or []
    policy_reasoning = state.get("policy_reasoning") or ""

    is_product_mismatch = (
        "product_mismatch" in failed_rules
        or (
            policy_status == "ambiguous"
            and (
                "product mismatch" in policy_reasoning.lower()
                or "mismatched product" in policy_reasoning.lower()
            )
        )
    )

    if is_product_mismatch:
        count = state.get("clarification_count")
        if count is None:
            count = 0
        if count < 2:
            return "clarification"
        return "decision"

    if (
        category == "damaged"
        and policy_status == "ambiguous"
        and "physical_damage_verification" in failed_rules
    ):
        count = state.get("clarification_count")
        if count is None:
            count = 0
        if count < 2:
            return "clarification"
        return "decision"

    return "decision"


def build_refund_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Assemble and compile the multi-agent LangGraph refund processing workflow.

    Args:
        checkpointer: Optional LangGraph checkpoint saver instance.

    Returns:
        CompiledStateGraph ready for execution.
    """
    builder = StateGraph(RefundWorkflowState)

    # Register workflow nodes
    builder.add_node("intake", intake_validate_node)
    builder.add_node("classifier", classifier_node)
    builder.add_node("clarification", clarification_node)
    builder.add_node("policy_checker", policy_checker_node)
    builder.add_node("decision", decision_node)
    builder.add_node("save_dynamo", save_dynamo_node)

    # Establish linear and conditional edges
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "classifier")

    # Conditional edge after classification
    builder.add_conditional_edges(
        "classifier",
        route_classifier,
        {
            "clarification": "clarification",
            "policy_checker": "policy_checker",
            "decision": "decision",
        },
    )

    # Clarification pauses workflow execution at END
    builder.add_edge("clarification", END)

    # Conditional edge after policy check
    builder.add_conditional_edges(
        "policy_checker",
        route_policy_check,
        {
            "clarification": "clarification",
            "decision": "decision",
        },
    )

    builder.add_edge("decision", "save_dynamo")
    builder.add_edge("save_dynamo", END)

    return builder.compile(checkpointer=checkpointer)
