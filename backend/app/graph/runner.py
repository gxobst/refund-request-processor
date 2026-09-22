"""Execution runner for the compiled refund workflow graph."""

from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core.config import get_settings
from app.graph.checkpoint import get_checkpointer
from app.graph.nodes import set_current_repository
from app.graph.state import RefundWorkflowState
from app.graph.workflow import build_refund_graph


async def run_refund_workflow(
    refund_id: str,
    order_id: str,
    customer_request_text: str,
    thread_id: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    repository: Any = None,
    use_dynamodb: bool | None = None,
) -> dict[str, Any]:
    """Execute the multi-agent refund evaluation workflow asynchronously.

    Args:
        refund_id: Unique refund request identifier.
        order_id: Associated order identifier.
        customer_request_text: Customer explanation text.
        thread_id: Optional thread ID for checkpointer tracking. Defaults to refund_id.
        checkpointer: Optional BaseCheckpointSaver. If provided, used directly.
        repository: Optional repository instance for database operations.
        use_dynamodb: Optional bool indicating whether to enable DynamoDB checkpointing.
            Defaults to True in non-test environments if checkpointer is None.

    Returns:
        Final state dictionary containing decision, reasoning, and status.
    """
    if checkpointer is not None:
        effective_checkpointer = checkpointer
    else:
        settings = get_settings()
        if use_dynamodb is None:
            use_dynamodb = settings.app_env != "test"
        effective_checkpointer = get_checkpointer(
            use_dynamodb=use_dynamodb, settings=settings
        )

    graph = build_refund_graph(checkpointer=effective_checkpointer)

    initial_state: dict[str, Any] = {
        "refund_id": refund_id,
        "order_id": order_id,
        "customer_request_text": customer_request_text,
        "status": "pending",
    }
    if repository is not None:
        set_current_repository(repository)

    config = {"configurable": {"thread_id": thread_id or refund_id}}
    final_state = await graph.ainvoke(initial_state, config=config)
    return final_state
