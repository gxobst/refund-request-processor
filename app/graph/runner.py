"""Execution runner for the compiled refund workflow graph."""

from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.graph.checkpoint import get_checkpointer
from app.graph.state import RefundWorkflowState
from app.graph.workflow import build_refund_graph


async def run_refund_workflow(
    refund_id: str,
    order_id: str,
    customer_request_text: str,
    thread_id: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    repository: Any = None,
) -> dict[str, Any]:
    """Execute the multi-agent refund evaluation workflow asynchronously.

    Args:
        refund_id: Unique refund request identifier.
        order_id: Associated order identifier.
        customer_request_text: Customer explanation text.
        thread_id: Optional thread ID for checkpointer tracking. Defaults to refund_id.
        checkpointer: Optional BaseCheckpointSaver. Defaults to in-memory checkpointer.
        repository: Optional repository instance for database operations.

    Returns:
        Final state dictionary containing decision, reasoning, and status.
    """
    effective_checkpointer = checkpointer or get_checkpointer(use_dynamodb=False)
    graph = build_refund_graph(checkpointer=effective_checkpointer)

    initial_state: dict[str, Any] = {
        "refund_id": refund_id,
        "order_id": order_id,
        "customer_request_text": customer_request_text,
        "status": "pending",
    }
    if repository is not None:
        initial_state["_repository"] = repository

    config = {"configurable": {"thread_id": thread_id or refund_id}}
    final_state = await graph.ainvoke(initial_state, config=config)
    return final_state
