"""LangGraph workflow assembly for refund request processing."""

from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes import (
    classifier_node,
    decision_node,
    intake_validate_node,
    policy_checker_node,
    save_dynamo_node,
)
from app.graph.state import RefundWorkflowState


def route_policy_check(state: RefundWorkflowState) -> str:
    """Conditional router following policy checking.

    Routes ambiguous and deterministic results to the decision node for
    automated resolution or escalation handling.
    """
    if state.get("policy_status") == "ambiguous":
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
    builder.add_node("policy_checker", policy_checker_node)
    builder.add_node("decision", decision_node)
    builder.add_node("save_dynamo", save_dynamo_node)

    # Establish linear and conditional edges
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "classifier")
    builder.add_edge("classifier", "policy_checker")

    # Conditional edge after policy check
    builder.add_conditional_edges(
        "policy_checker",
        route_policy_check,
        {"decision": "decision"},
    )

    builder.add_edge("decision", "save_dynamo")
    builder.add_edge("save_dynamo", END)

    return builder.compile(checkpointer=checkpointer)
