"""Node implementations for the LangGraph refund workflow."""

import json
from pathlib import Path
from typing import Any

from app.agents.classifier import classifier_node as agent_classifier_node
from app.agents.decision import decision_node as agent_decision_node
from app.agents.policy_checker import policy_checker_node as agent_policy_checker_node
from app.db.repository import RefundNotFoundError, RefundRepository

MOCK_ORDERS_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_orders.json"


def _lookup_order_data(order_id: str) -> dict[str, Any] | None:
    """Helper to locate order details by order_id from the mock dataset."""
    if not order_id or not MOCK_ORDERS_PATH.is_file():
        return None

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
        Dictionary update with 'order' and 'missing_order_data'.
    """
    order = state.get("order")
    order_id = state.get("order_id", "")

    if order is None:
        order = _lookup_order_data(order_id)

    missing_order_data = order is None

    return {
        "order": order,
        "missing_order_data": missing_order_data,
    }


def classifier_node(state: dict[str, Any]) -> dict[str, Any]:
    """Classify customer refund request reason."""
    return agent_classifier_node(state)


def policy_checker_node(state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate order against refund policy rules."""
    if state.get("missing_order_data") or not state.get("order"):
        return {
            "policy_status": "ambiguous",
            "matched_policy_rule": None,
            "policy_reasoning": "Missing required order data.",
            "passed_rules": [],
            "failed_rules": [],
        }
    return agent_policy_checker_node(state)



def decision_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthesize findings into final approval, denial, or escalation decision."""
    return agent_decision_node(state)


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

    if refund_id:
        repo = state.get("_repository") or RefundRepository()
        try:
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

    return {"status": status}
