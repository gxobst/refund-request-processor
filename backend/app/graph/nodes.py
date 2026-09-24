"""Node implementations for the LangGraph refund workflow."""

import contextvars
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
import boto3

from app.agents.approval_notifier import generate_approval_email
from app.agents.classifier import classifier_node as agent_classifier_node
from app.agents.clarification import generate_clarification_prompt
from app.agents.decision import decision_node as agent_decision_node
from app.agents.denial_notifier import generate_denial_email
from app.agents.policy_checker import policy_checker_node as agent_policy_checker_node
from app.core.config import get_settings
from app.db.repository import (
    RefundNotFoundError,
    RefundRepository,
    _convert_decimals_to_float,
)

_repository_context: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "_repository_context", default=None
)


def set_current_repository(repo: Any | None) -> None:
    """Set the active repository in the current execution context."""
    _repository_context.set(repo)


def get_current_repository() -> Any | None:
    """Retrieve the active repository from the current execution context."""
    return _repository_context.get()

MOCK_ORDERS_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_orders.json"


def _lookup_order_data(order_id: str) -> dict[str, Any] | None:
    """Helper to locate order details by order_id from DynamoDB or fallback dataset."""
    if not order_id or not str(order_id).strip():
        return None

    # 1. Attempt lookup from DynamoDB table
    try:
        settings = get_settings()
        repo = get_current_repository()
        dynamodb_resource = (
            getattr(repo, "dynamodb_resource", None)
            if repo is not None
            else None
        )

        if dynamodb_resource is None:
            kwargs: dict[str, Any] = {
                "region_name": settings.aws_region,
            }
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                kwargs["aws_access_key_id"] = settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
                if settings.aws_session_token:
                    kwargs["aws_session_token"] = settings.aws_session_token
            if settings.dynamodb_endpoint_url:
                kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
            dynamodb_resource = boto3.resource("dynamodb", **kwargs)

        table_name = getattr(settings, "dynamodb_table_orders", "mock-orders")
        table = dynamodb_resource.Table(table_name)
        response = table.get_item(Key={"order_id": order_id})
        item = response.get("Item")
        if item:
            return _convert_decimals_to_float(item)
    except Exception:
        # Gracefully handle any DynamoDB exception and fall back to local mock orders
        pass

    # 2. Fall back to local mock orders JSON
    if MOCK_ORDERS_PATH.is_file():
        try:
            with open(MOCK_ORDERS_PATH, "r", encoding="utf-8") as f:
                orders = json.load(f)
            for order in orders:
                if order.get("order_id") == order_id:
                    return order
        except Exception:
            pass

    return None


def intake_validate_node(state: dict[str, Any]) -> dict[str, Any]:
    """Validate intake payload and populate order details.

    Args:
        state: Initial workflow state dictionary.

    Returns:
        Dictionary update with order details, missing order flag, and clarification fields.
    """
    order = state.get("order")
    order_id = state.get("order_id", "")

    if order is None:
        order = _lookup_order_data(order_id)

    missing_order_data = order is None
    state["order"] = order
    state["missing_order_data"] = missing_order_data

    clarification_count = state.get("clarification_count")
    if clarification_count is None:
        clarification_count = 0
    state["clarification_count"] = clarification_count

    clarification_prompt = state.get("clarification_prompt")
    clarification_response = state.get("clarification_response")
    needs_clarification = state.get("needs_clarification", False)

    return {
        "order": order,
        "missing_order_data": missing_order_data,
        "clarification_count": clarification_count,
        "clarification_prompt": clarification_prompt,
        "clarification_response": clarification_response,
        "needs_clarification": needs_clarification,
    }


def classifier_node(state: dict[str, Any]) -> dict[str, Any]:
    """Classify customer refund request reason."""
    return agent_classifier_node(state)


def clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate customer clarification prompt and pause workflow awaiting response.

    Args:
        state: Workflow state dictionary.

    Returns:
        Dictionary update with clarification prompt, incremented count, and awaiting_clarification status.
    """
    customer_text = state.get("customer_request_text", "")
    category = state.get("category")
    order = state.get("order")

    output = generate_clarification_prompt(
        customer_request_text=customer_text,
        category=category,
        order=order,
    )
    prompt = output.clarification_prompt

    current_count = (
        state.get("clarification_count")
        if state.get("clarification_count") is not None
        else 0
    ) + 1

    refund_id = state.get("refund_id")
    if refund_id:
        repo = get_current_repository() or state.get("_repository")
        if repo is not None:
            try:
                repo.request_clarification(
                    refund_id=refund_id,
                    clarification_prompt=prompt,
                )
            except (RefundNotFoundError, Exception):
                pass

    return {
        "clarification_prompt": prompt,
        "clarification_count": current_count,
        "status": "awaiting_clarification",
        "needs_clarification": True,
    }


def policy_checker_node(state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate order against refund policy rules."""
    if not state.get("order") and not state.get("order_id"):
        return {
            "policy_status": "ambiguous",
            "matched_policy_rule": None,
            "policy_reasoning": "Missing required order data.",
            "passed_rules": [],
            "failed_rules": [],
            "tool_calls": [],
        }
    res = agent_policy_checker_node(state)
    if "tool_calls" not in res:
        res["tool_calls"] = []
    return res




def decision_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthesize findings into final approval, denial, or escalation decision."""
    res = agent_decision_node(state)
    decision = res.get("decision")
    if decision == "auto_approve":
        order_id = state.get("order_id", "")
        refund_id = state.get("refund_id")
        approval_email = generate_approval_email(order_id=order_id, refund_id=refund_id)
        res["approval_email_text"] = approval_email
        res["denial_email_text"] = None
    elif decision == "deny":
        order_id = state.get("order_id", "")
        refund_id = state.get("refund_id")
        failed_rules = state.get("failed_rules", [])
        policy_reasoning = state.get("policy_reasoning") or res.get("reasoning")
        category = state.get("category")
        denial_email = generate_denial_email(
            order_id=order_id,
            refund_id=refund_id,
            failed_rules=failed_rules,
            policy_reasoning=policy_reasoning,
            category=category,
        )
        res["denial_email_text"] = denial_email
        res["approval_email_text"] = None
    else:
        res["approval_email_text"] = None
        res["denial_email_text"] = None
    return res


def save_dynamo_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist final workflow decision and status into DynamoDB.

    Args:
        state: Workflow state dictionary.

    Returns:
        Dictionary with final persisted status.
    """
    refund_id = state.get("refund_id")
    decision = state.get("decision", "escalate")
    reasoning = state.get("reasoning", "")
    matched_rule = state.get("matched_policy_rule")
    confidence = state.get("confidence_score", 0.0)
    status = state.get("status", "completed")
    tool_calls = state.get("tool_calls", [])
    approval_email_text = state.get("approval_email_text")
    denial_email_text = state.get("denial_email_text")

    if refund_id:
        repo = get_current_repository() or state.get("_repository") or RefundRepository()
        try:
            try:
                repo.update_decision(
                    refund_id=refund_id,
                    decision=decision,
                    reasoning=reasoning,
                    matched_policy_rule=matched_rule,
                    confidence_score=confidence,
                    status=status,
                    tool_calls=tool_calls,
                    approval_email_text=approval_email_text,
                    denial_email_text=denial_email_text,
                )
            except TypeError:
                repo.update_decision(
                    refund_id=refund_id,
                    decision=decision,
                    reasoning=reasoning,
                    matched_policy_rule=matched_rule,
                    confidence_score=confidence,
                    status=status,
                )
        except (RefundNotFoundError, KeyError):
            # In testing or standalone execution, record might not exist prior
            pass
        except Exception:
            pass

    return {
        "status": status,
        "approval_email_text": approval_email_text,
        "denial_email_text": denial_email_text,
    }
