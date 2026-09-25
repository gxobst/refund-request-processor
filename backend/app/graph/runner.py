"""Execution runner for the compiled refund workflow graph."""

from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core.config import get_settings
from app.graph.checkpoint import get_checkpointer
from app.graph.nodes import _lookup_order_data, set_current_repository
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
    callbacks: list[Any] | None = None,
    evidence: list[dict[str, Any] | Any] | None = None,
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
        callbacks: Optional list of callback handlers for tracing.
        evidence: Optional list of attached evidence metadata items or dicts.

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

    initial_evidence: list[dict[str, Any]] = []
    if evidence:
        for item in evidence:
            if hasattr(item, "model_dump"):
                initial_evidence.append(item.model_dump())
            elif isinstance(item, dict):
                initial_evidence.append(item)
            else:
                initial_evidence.append(dict(item))

    initial_state: dict[str, Any] = {
        "refund_id": refund_id,
        "order_id": order_id,
        "customer_request_text": customer_request_text,
        "status": "pending",
        "evidence": initial_evidence,
    }
    if repository is not None:
        set_current_repository(repository)

    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id or refund_id},
        "metadata": {"refund_id": refund_id, "order_id": order_id},
        "tags": ["refund-workflow"],
    }
    if callbacks is not None:
        config["callbacks"] = callbacks

    final_state = await graph.ainvoke(initial_state, config=config)
    return final_state


async def resume_refund_workflow(
    refund_id: str,
    response_text: str,
    thread_id: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    repository: Any = None,
    use_dynamodb: bool | None = None,
    callbacks: list[Any] | None = None,
) -> dict[str, Any]:
    """Resume the multi-agent refund evaluation workflow upon customer clarification.

    Args:
        refund_id: Unique refund request identifier.
        response_text: Customer clarification response text.
        thread_id: Optional thread ID for checkpointer tracking. Defaults to refund_id.
        checkpointer: Optional BaseCheckpointSaver. If provided, used directly.
        repository: Optional repository instance for database operations.
        use_dynamodb: Optional bool indicating whether to enable DynamoDB checkpointing.
            Defaults to True in non-test environments if checkpointer is None.
        callbacks: Optional list of callback handlers for tracing.

    Returns:
        Final state dictionary containing decision, reasoning, and status.
    """
    if repository is not None:
        set_current_repository(repository)

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
    target_thread_id = thread_id or refund_id
    config: dict[str, Any] = {"configurable": {"thread_id": target_thread_id}}

    snapshot = await graph.aget_state(config)
    existing_state = dict(snapshot.values) if snapshot and snapshot.values else {}

    if not existing_state and repository is not None:
        record = repository.get_refund_request(refund_id)
        if record is not None:
            order_data = _lookup_order_data(record.order_id)
            existing_state = {
                "refund_id": record.refund_id,
                "order_id": record.order_id,
                "customer_request_text": record.customer_request_text,
                "order": order_data,
                "missing_order_data": order_data is None,
                "clarification_count": record.clarification_count or 1,
                "evidence": [
                    e.model_dump() if hasattr(e, "model_dump") else e
                    for e in (record.evidence or [])
                ],
            }

    if not existing_state:
        existing_state = {
            "refund_id": refund_id,
            "customer_request_text": "",
            "clarification_count": 1,
        }

    order_id = existing_state.get("order_id", "")
    config["metadata"] = {"refund_id": refund_id, "order_id": order_id}
    config["tags"] = ["refund-workflow"]
    if callbacks is not None:
        config["callbacks"] = callbacks

    original_text = existing_state.get("customer_request_text", "")
    combined_text = (
        f"{original_text}\n[Clarification]: {response_text}"
        if original_text
        else f"[Clarification]: {response_text}"
    )

    state_update: dict[str, Any] = {
        **existing_state,
        "customer_request_text": combined_text,
        "clarification_response": response_text,
        "status": "pending",
        "needs_clarification": False,
    }

    await graph.aupdate_state(config, state_update, as_node="intake")
    final_state = await graph.ainvoke(None, config=config)

    if repository is not None and final_state.get("status") in ("completed", "escalated"):
        try:
            try:
                repository.update_decision(
                    refund_id=refund_id,
                    decision=final_state.get("decision", "escalate"),
                    reasoning=final_state.get("reasoning", ""),
                    matched_policy_rule=final_state.get("matched_policy_rule"),
                    confidence_score=final_state.get("confidence_score", 0.0),
                    status=final_state.get("status", "completed"),
                    tool_calls=final_state.get("tool_calls"),
                )
            except TypeError:
                repository.update_decision(
                    refund_id=refund_id,
                    decision=final_state.get("decision", "escalate"),
                    reasoning=final_state.get("reasoning", ""),
                    matched_policy_rule=final_state.get("matched_policy_rule"),
                    confidence_score=final_state.get("confidence_score", 0.0),
                    status=final_state.get("status", "completed"),
                )
        except Exception:
            pass

    return final_state
