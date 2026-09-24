"""DynamoDB repository for refund requests and decisions."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import uuid
import boto3

from app.core.config import get_settings
from app.schemas.refund import RefundRecord


class RefundNotFoundError(KeyError):
    """Raised when a refund request is not found in the database."""

    pass


def _convert_floats_to_decimal(val: Any, preserve_none: bool = False) -> Any:
    """Recursively convert float values to Decimal for DynamoDB storage."""
    if isinstance(val, float):
        return Decimal(str(val))
    if isinstance(val, dict):
        if preserve_none:
            return {k: _convert_floats_to_decimal(v, True) for k, v in val.items()}
        return {
            k: _convert_floats_to_decimal(v, preserve_none=True)
            for k, v in val.items()
            if v is not None
        }
    if isinstance(val, list):
        return [_convert_floats_to_decimal(v, True) for v in val]
    return val


def _convert_decimals_to_float(val: Any) -> Any:
    """Recursively convert Decimal values back to float/int for Python/Pydantic."""
    if isinstance(val, Decimal):
        return int(val) if val % 1 == 0 else float(val)
    if isinstance(val, dict):
        return {k: _convert_decimals_to_float(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_convert_decimals_to_float(v) for v in val]
    return val


class RefundRepository:
    """Data access repository for managing refund request lifecycles in DynamoDB."""

    def __init__(self, dynamodb_resource: Any = None, table_name: str | None = None) -> None:
        if table_name is None or dynamodb_resource is None:
            settings = get_settings()
        else:
            settings = None

        if table_name is not None:
            self.table_name = table_name
        else:
            self.table_name = settings.dynamodb_table_refunds

        if dynamodb_resource is not None:
            self.dynamodb_resource = dynamodb_resource
        else:
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

            self.dynamodb_resource = boto3.resource("dynamodb", **kwargs)

        self.table = self.dynamodb_resource.Table(self.table_name)

    def create_refund_request(self, order_id: str, customer_request_text: str) -> RefundRecord:
        """Create and persist a new refund request record.

        Args:
            order_id: Associated order identifier.
            customer_request_text: Customer-provided refund explanation.

        Returns:
            The created RefundRecord instance.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        refund_id = f"ref_{uuid.uuid4().hex[:12]}"

        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text,
            status="pending",
            created_at=now_iso,
            updated_at=now_iso,
            clarification_prompt=None,
            clarification_response=None,
            clarification_count=0,
            tool_calls=[],
        )

        item = _convert_floats_to_decimal(record.model_dump())
        self.table.put_item(Item=item)
        return record

    def get_refund_request(self, refund_id: str) -> RefundRecord | None:
        """Retrieve a single refund request by ID.

        Args:
            refund_id: Partition key identifier.

        Returns:
            RefundRecord instance if found, None otherwise.
        """
        response = self.table.get_item(Key={"refund_id": refund_id})
        item = response.get("Item")
        if not item:
            return None

        cleaned = _convert_decimals_to_float(item)
        return RefundRecord.model_validate(cleaned)

    def list_refund_requests(self, status: str | None = None, limit: int = 50) -> list[RefundRecord]:
        """List refund requests with optional status filtering.

        Args:
            status: Optional status to filter by ('pending', 'completed', 'escalated', 'awaiting_clarification').
            limit: Maximum number of records to return.

        Returns:
            List of matching RefundRecord instances.
        """
        response = self.table.scan()
        raw_items = response.get("Items", [])

        records = [
            RefundRecord.model_validate(_convert_decimals_to_float(item))
            for item in raw_items
        ]

        if status is not None:
            status_lower = status.strip().lower()
            records = [r for r in records if r.status.lower() == status_lower]

        # Sort descending by created_at
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]

    def update_decision(
        self,
        refund_id: str,
        decision: str,
        reasoning: str,
        matched_policy_rule: dict[str, Any] | None,
        confidence_score: float,
        status: str,
        tool_calls: list[dict[str, Any]] | None = None,
        approval_email_text: str | None = None,
    ) -> RefundRecord:
        """Update decision metadata and workflow status for an existing refund record.

        Args:
            refund_id: Target refund record ID.
            decision: Automated decision ('auto_approve', 'deny', 'escalate').
            reasoning: Reasoning text for the decision.
            matched_policy_rule: Evaluated policy rule dict or None.
            confidence_score: Float confidence score between 0.0 and 1.0.
            status: Workflow status ('completed' or 'escalated').
            tool_calls: Optional list of executed tool call audit dictionaries.
            approval_email_text: Optional generated confirmation and return instructions email text.

        Returns:
            Updated RefundRecord instance.

        Raises:
            RefundNotFoundError: If the refund request does not exist.
        """
        existing = self.get_refund_request(refund_id)
        if existing is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = existing.model_dump()
        updated_dict["decision"] = decision
        updated_dict["reasoning"] = reasoning
        updated_dict["matched_policy_rule"] = matched_policy_rule
        updated_dict["confidence_score"] = confidence_score
        updated_dict["status"] = status
        updated_dict["updated_at"] = now_iso
        if tool_calls is not None:
            updated_dict["tool_calls"] = tool_calls
        else:
            updated_dict["tool_calls"] = existing.tool_calls or []

        if approval_email_text is not None:
            updated_dict["approval_email_text"] = approval_email_text
        elif decision != "auto_approve":
            updated_dict["approval_email_text"] = None
        else:
            updated_dict["approval_email_text"] = existing.approval_email_text

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def apply_override(
        self,
        refund_id: str,
        override_decision: str,
        override_reason: str,
        approval_email_text: str | None = None,
    ) -> RefundRecord:
        """Record a human manual override and update final decision.

        Args:
            refund_id: Target refund request ID.
            override_decision: Human override decision ('approve' or 'deny').
            override_reason: Justification for the override.
            approval_email_text: Optional custom or pre-generated approval email text.

        Returns:
            Updated RefundRecord instance.

        Raises:
            RefundNotFoundError: If the refund request does not exist.
        """
        existing = self.get_refund_request(refund_id)
        if existing is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = existing.model_dump()
        updated_dict["override_decision"] = override_decision
        updated_dict["override_reason"] = override_reason
        updated_dict["overridden_at"] = now_iso
        updated_dict["updated_at"] = now_iso
        updated_dict["decision"] = override_decision
        updated_dict["status"] = "completed"

        if override_decision in ("approve", "auto_approve"):
            if approval_email_text is None:
                from app.agents.approval_notifier import generate_approval_email
                approval_email_text = generate_approval_email(order_id=existing.order_id, refund_id=refund_id)
            updated_dict["approval_email_text"] = approval_email_text
        else:
            updated_dict["approval_email_text"] = None

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def request_clarification(
        self,
        refund_id: str,
        clarification_prompt: str,
    ) -> RefundRecord:
        """Update refund request to awaiting_clarification with a clarification prompt.

        Args:
            refund_id: Target refund request ID.
            clarification_prompt: Clarification question for the customer.

        Returns:
            Updated RefundRecord instance.

        Raises:
            ValueError: If clarification_prompt is empty or whitespace-only.
            RefundNotFoundError: If the refund request does not exist.
        """
        if not clarification_prompt or not clarification_prompt.strip():
            raise ValueError("clarification_prompt cannot be blank or empty.")

        existing = self.get_refund_request(refund_id)
        if existing is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = existing.model_dump()
        updated_dict["status"] = "awaiting_clarification"
        updated_dict["clarification_prompt"] = clarification_prompt.strip()
        updated_dict["clarification_count"] = (existing.clarification_count or 0) + 1
        updated_dict["updated_at"] = now_iso

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def submit_clarification_response(
        self,
        refund_id: str,
        clarification_response: str,
    ) -> RefundRecord:
        """Record customer clarification response and return status to pending.

        Args:
            refund_id: Target refund request ID.
            clarification_response: Customer-provided clarification details.

        Returns:
            Updated RefundRecord instance.

        Raises:
            ValueError: If clarification_response is empty or whitespace-only.
            RefundNotFoundError: If the refund request does not exist.
        """
        if not clarification_response or not clarification_response.strip():
            raise ValueError("clarification_response cannot be blank or empty.")

        existing = self.get_refund_request(refund_id)
        if existing is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = existing.model_dump()
        updated_dict["status"] = "pending"
        updated_dict["clarification_response"] = clarification_response.strip()
        updated_dict["updated_at"] = now_iso

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

