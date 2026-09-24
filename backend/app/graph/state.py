"""State schema definitions for the LangGraph refund evaluation workflow."""

from typing import Any, TypedDict


class RefundWorkflowState(TypedDict, total=False):
    """Complete workflow state dictionary passed across LangGraph nodes."""

    refund_id: str
    order_id: str
    customer_request_text: str
    order: dict[str, Any] | None
    category: str | None
    classification_confidence: float | None
    confidence_score: float | None
    is_low_confidence: bool
    policy_status: str | None
    matched_policy_rule: dict[str, Any] | None
    passed_rules: list[str]
    failed_rules: list[str]
    policy_reasoning: str | None
    missing_order_data: bool
    policy_conflict: bool
    decision: str | None
    decision_reasoning: str | None
    reasoning: str | None
    status: str
    clarification_prompt: str | None
    clarification_response: str | None
    clarification_count: int
    needs_clarification: bool
    tool_calls: list[dict[str, Any]]
    approval_email_text: str | None
    denial_email_text: str | None
    evidence: list[dict[str, Any]] | list[Any]
