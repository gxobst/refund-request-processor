"""DynamoDB repository for refund requests and decisions."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
import uuid
import boto3

from app.core.config import get_settings
from app.schemas.analytics import (
    AnalyticsMetricsResponse,
    AnalyticsTrendsResponse,
    DecisionBreakdown,
    StatusBreakdown,
    TrendDataPoint,
)
from app.schemas.refund import ClarificationTurn, EvidenceItem, RefundRecord


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


def _filter_items_by_date_range(
    raw_items: list[dict],
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Filter raw DynamoDB items by created_at falling within [start_date, end_date] (inclusive)."""
    if not start_date and not end_date:
        return raw_items

    filtered: list[dict] = []
    for item in raw_items:
        created_at = item.get("created_at")
        if not created_at or not isinstance(created_at, str):
            continue
        created_at_str = created_at.strip()
        if not created_at_str:
            continue

        # Check start_date
        if start_date:
            if len(start_date) == 10:
                if created_at_str[:10] < start_date:
                    continue
            else:
                if created_at_str < start_date:
                    continue

        # Check end_date (inclusive through end of day if 10-char YYYY-MM-DD)
        if end_date:
            if len(end_date) == 10:
                if created_at_str[:10] > end_date:
                    continue
            else:
                if created_at_str > end_date:
                    continue

        filtered.append(item)
    return filtered


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
        self._table = self.table

    def create_refund_request(
        self,
        order_id: str,
        customer_request_text: str,
        evidence: list[EvidenceItem | dict[str, Any]] | None = None,
    ) -> RefundRecord:
        """Create and persist a new refund request record.

        Args:
            order_id: Associated order identifier.
            customer_request_text: Customer-provided refund explanation.
            evidence: Optional initial evidence items or dicts.

        Returns:
            The created RefundRecord instance.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        refund_id = f"ref_{uuid.uuid4().hex[:12]}"

        evidence_items: list[EvidenceItem] = []
        if evidence:
            for item in evidence:
                if isinstance(item, EvidenceItem):
                    evidence_items.append(item)
                elif isinstance(item, dict):
                    evidence_items.append(EvidenceItem.model_validate(item))
                else:
                    raise TypeError("evidence item must be an EvidenceItem or dict.")

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
            evidence=evidence_items,
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
        denial_email_text: str | None = None,
        category: str | None = None,
        node_latencies: dict[str, float] | None = None,
        latency_ms: float | None = None,
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
            denial_email_text: Optional generated denial notification email text.
            category: Optional classified refund reason category.
            node_latencies: Optional dict of wall-clock latencies per agent node in milliseconds.
            latency_ms: Optional total workflow evaluation latency in milliseconds.

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
        if category is not None:
            updated_dict["category"] = category
        if tool_calls is not None:
            updated_dict["tool_calls"] = tool_calls
        else:
            updated_dict["tool_calls"] = existing.tool_calls or []

        if node_latencies is not None:
            updated_dict["node_latencies"] = node_latencies
        else:
            updated_dict["node_latencies"] = existing.node_latencies or {}

        if latency_ms is not None:
            updated_dict["latency_ms"] = latency_ms
        else:
            updated_dict["latency_ms"] = existing.latency_ms

        if approval_email_text is not None:
            updated_dict["approval_email_text"] = approval_email_text
        elif decision != "auto_approve":
            updated_dict["approval_email_text"] = None
        else:
            updated_dict["approval_email_text"] = existing.approval_email_text

        if denial_email_text is not None:
            updated_dict["denial_email_text"] = denial_email_text
        elif decision != "deny":
            updated_dict["denial_email_text"] = None
        else:
            updated_dict["denial_email_text"] = existing.denial_email_text

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def apply_override(
        self,
        refund_id: str,
        override_decision: str,
        override_reason: str,
        approval_email_text: str | None = None,
        denial_email_text: str | None = None,
        overridden_by: str | None = "supervisor",
    ) -> RefundRecord:
        """Record a human manual override and update final decision.

        Args:
            refund_id: Target refund request ID.
            override_decision: Human override decision ('approve' or 'deny').
            override_reason: Justification for the override.
            approval_email_text: Optional custom or pre-generated approval email text.
            denial_email_text: Optional custom or pre-generated denial email text.
            overridden_by: Identifier or role of the operator who applied the manual override.

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
        updated_dict["overridden_by"] = overridden_by
        updated_dict["updated_at"] = now_iso
        updated_dict["decision"] = override_decision
        updated_dict["status"] = "completed"

        if override_decision in ("approve", "auto_approve"):
            if approval_email_text is None:
                from app.agents.approval_notifier import generate_approval_email
                approval_email_text = generate_approval_email(order_id=existing.order_id, refund_id=refund_id)
            updated_dict["approval_email_text"] = approval_email_text
            updated_dict["denial_email_text"] = None
        elif override_decision == "deny":
            if denial_email_text is None:
                from app.agents.denial_notifier import generate_denial_email
                denial_email_text = generate_denial_email(
                    order_id=existing.order_id,
                    refund_id=refund_id,
                    policy_reasoning=override_reason,
                )
            updated_dict["denial_email_text"] = denial_email_text
            updated_dict["approval_email_text"] = None
        else:
            updated_dict["approval_email_text"] = None
            updated_dict["denial_email_text"] = None

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def request_clarification(
        self,
        refund_id: str,
        clarification_prompt: str,
        category: str | None = None,
        confidence_score: float | None = None,
        reasoning: str | None = None,
    ) -> RefundRecord:
        """Update refund request to awaiting_clarification with a clarification prompt.

        Args:
            refund_id: Target refund request ID.
            clarification_prompt: Clarification question for the customer.
            category: Optional classified refund reason category.
            confidence_score: Optional model confidence score between 0.0 and 1.0.
            reasoning: Optional classification or evaluation reasoning.

        Returns:
            Updated RefundRecord instance.

        Raises:
            ValueError: If clarification_prompt is empty or whitespace-only, or confidence_score is invalid.
            RefundNotFoundError: If the refund request does not exist.
        """
        if not clarification_prompt or not clarification_prompt.strip():
            raise ValueError("clarification_prompt cannot be blank or empty.")

        if confidence_score is not None:
            if not (0.0 <= confidence_score <= 1.0):
                raise ValueError(
                    f"confidence_score must be between 0.0 and 1.0, got {confidence_score}"
                )

        existing = self.get_refund_request(refund_id)
        if existing is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = existing.model_dump()
        new_count = (existing.clarification_count or 0) + 1
        updated_dict["status"] = "awaiting_clarification"
        updated_dict["decision"] = None
        updated_dict["clarification_prompt"] = clarification_prompt.strip()
        updated_dict["clarification_count"] = new_count
        updated_dict["updated_at"] = now_iso

        history = list(updated_dict.get("clarification_history") or [])
        history.append({
            "cycle": new_count,
            "prompt": clarification_prompt.strip(),
            "response": None,
            "timestamp": now_iso,
            "evidence_ids": [],
        })
        updated_dict["clarification_history"] = history

        if category is not None:
            updated_dict["category"] = category
        if confidence_score is not None:
            updated_dict["confidence_score"] = confidence_score
        if reasoning is not None:
            updated_dict["reasoning"] = reasoning

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

        history = list(updated_dict.get("clarification_history") or [])
        current_cycle = existing.clarification_count or 1
        found = False
        for turn in reversed(history):
            if turn.get("cycle") == current_cycle:
                turn["response"] = clarification_response.strip()
                found = True
                break
        if not found:
            if history:
                history[-1]["response"] = clarification_response.strip()
            else:
                history.append({
                    "cycle": current_cycle,
                    "prompt": existing.clarification_prompt,
                    "response": clarification_response.strip(),
                    "timestamp": now_iso,
                    "evidence_ids": [],
                })
        updated_dict["clarification_history"] = history

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def add_evidence(
        self,
        refund_id: str,
        evidence_item: EvidenceItem | dict[str, Any],
    ) -> RefundRecord:
        """Append an evidence attachment item to an existing refund record.

        Args:
            refund_id: Target refund request ID.
            evidence_item: EvidenceItem instance or equivalent dict.

        Returns:
            Updated RefundRecord instance.

        Raises:
            RefundNotFoundError: If the refund request does not exist.
        """
        existing = self.get_refund_request(refund_id)
        if existing is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")

        if isinstance(evidence_item, EvidenceItem):
            item_dict = evidence_item.model_dump()
        elif isinstance(evidence_item, dict):
            item_dict = EvidenceItem.model_validate(evidence_item).model_dump()
        else:
            raise TypeError("evidence_item must be an EvidenceItem or dict.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = existing.model_dump()
        current_evidence = list(updated_dict.get("evidence") or [])
        current_evidence.append(item_dict)
        updated_dict["evidence"] = current_evidence
        updated_dict["updated_at"] = now_iso

        history = list(updated_dict.get("clarification_history") or [])
        if history:
            ev_id = item_dict.get("evidence_id")
            if ev_id:
                ev_ids = list(history[-1].get("evidence_ids") or [])
                if ev_id not in ev_ids:
                    ev_ids.append(ev_id)
                history[-1]["evidence_ids"] = ev_ids
        updated_dict["clarification_history"] = history

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def request_reviewer_proof(
        self,
        refund_id: str,
        proof_prompt: str,
        notification_email_text: str | None = None,
    ) -> RefundRecord:
        """Transition an escalated refund request to awaiting_clarification with reviewer proof instructions.

        Args:
            refund_id: Target refund request ID.
            proof_prompt: Reviewer proof prompt or inquiry details.
            notification_email_text: Optional generated customer notification email text.

        Returns:
            Updated RefundRecord instance with status awaiting_clarification and decision reset to None.

        Raises:
            RefundNotFoundError: If the refund request does not exist.
            ValueError: If proof_prompt is blank or empty, or if current status is not 'escalated'.
        """
        if not proof_prompt or not proof_prompt.strip():
            raise ValueError("proof_prompt cannot be blank or empty.")

        existing = self.get_refund_request(refund_id)
        if existing is None:
            raise RefundNotFoundError(f"Refund request with id '{refund_id}' not found.")

        if existing.status != "escalated":
            raise ValueError(
                f"Refund request '{refund_id}' is not in 'escalated' status (current status: '{existing.status}')."
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = existing.model_dump()
        new_count = (existing.clarification_count or 0) + 1
        updated_dict["status"] = "awaiting_clarification"
        updated_dict["decision"] = None
        updated_dict["clarification_prompt"] = proof_prompt.strip()
        updated_dict["clarification_email_text"] = notification_email_text
        updated_dict["clarification_count"] = new_count
        updated_dict["updated_at"] = now_iso

        history = list(updated_dict.get("clarification_history") or [])
        history.append({
            "cycle": new_count,
            "prompt": proof_prompt.strip(),
            "response": None,
            "timestamp": now_iso,
            "evidence_ids": [],
        })
        updated_dict["clarification_history"] = history

        item = _convert_floats_to_decimal(updated_dict)
        self.table.put_item(Item=item)
        return RefundRecord.model_validate(updated_dict)

    def get_analytics_metrics(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AnalyticsMetricsResponse:
        """Scan DynamoDB refund records and compute aggregate operational and AI metrics."""
        table = getattr(self, "_table", self.table)
        response = table.scan()
        raw_items = response.get("Items", []) if isinstance(response, dict) else (response or [])

        raw_items = _filter_items_by_date_range(raw_items, start_date=start_date, end_date=end_date)

        total_requests = len(raw_items)
        if total_requests == 0:
            return AnalyticsMetricsResponse(
                total_requests=0,
                status_breakdown=StatusBreakdown(),
                decision_breakdown=DecisionBreakdown(),
                auto_approval_rate=0.0,
                override_rate=0.0,
                average_confidence=0.0,
                category_breakdown={},
                average_latency_ms=0.0,
                node_latency_breakdown={"classifier": 0.0, "policy_checker": 0.0, "decision_agent": 0.0},
            )

        status_counts = {
            "pending": 0,
            "completed": 0,
            "escalated": 0,
            "awaiting_clarification": 0,
        }
        decision_counts = {
            "auto_approve": 0,
            "deny": 0,
            "escalate": 0,
            "pending": 0,
        }
        category_breakdown: dict[str, int] = {}
        completed_records_count = 0
        completed_overridden_count = 0
        confidence_scores: list[float] = []
        latencies: list[float] = []
        node_latencies_collector: dict[str, list[float]] = {
            "classifier": [],
            "policy_checker": [],
            "decision_agent": [],
        }

        for item in raw_items:
            # Status breakdown
            raw_status = str(item.get("status") or "").strip().lower()
            if raw_status in status_counts:
                status_counts[raw_status] += 1

            # Decision breakdown (unfinalized, missing, or pending mapped to pending)
            raw_decision = str(item.get("decision") or "").strip().lower()
            if raw_decision in ("auto_approve", "deny", "escalate"):
                decision_counts[raw_decision] += 1
            else:
                decision_counts["pending"] += 1

            # Category breakdown (missing, null, or empty category mapped to "unclassified")
            raw_category = item.get("category")
            if raw_category is not None and str(raw_category).strip():
                cat_key = str(raw_category).strip()
            else:
                cat_key = "unclassified"
            category_breakdown[cat_key] = category_breakdown.get(cat_key, 0) + 1

            # Completed records for override rate calculation
            if raw_status == "completed":
                completed_records_count += 1
                if item.get("override_decision") is not None or item.get("overridden_at") is not None:
                    completed_overridden_count += 1

            # AI confidence score (convert Decimal to float if present)
            raw_conf = item.get("confidence_score")
            if raw_conf is not None:
                try:
                    confidence_scores.append(float(raw_conf))
                except (ValueError, TypeError):
                    pass

            # Latency metrics aggregation
            raw_lat = item.get("latency_ms")
            item_total_latency: float | None = None
            if raw_lat is not None:
                try:
                    item_total_latency = float(raw_lat)
                except (ValueError, TypeError):
                    item_total_latency = None

            raw_nl = item.get("node_latencies")
            if isinstance(raw_nl, dict):
                nl_sum = 0.0
                has_nl_values = False
                for node_key in ("classifier", "policy_checker", "decision_agent"):
                    val = raw_nl.get(node_key)
                    if val is not None:
                        try:
                            f_val = float(val)
                            node_latencies_collector[node_key].append(f_val)
                            nl_sum += f_val
                            has_nl_values = True
                        except (ValueError, TypeError):
                            pass
                if item_total_latency is None and has_nl_values:
                    item_total_latency = nl_sum

            if item_total_latency is not None:
                latencies.append(item_total_latency)

        auto_approval_rate = round(decision_counts["auto_approve"] / total_requests, 4)
        override_rate = (
            round(completed_overridden_count / completed_records_count, 4)
            if completed_records_count > 0
            else 0.0
        )
        average_confidence = (
            round(sum(confidence_scores) / len(confidence_scores), 4)
            if confidence_scores
            else 0.0
        )
        average_latency_ms = (
            round(sum(latencies) / len(latencies), 2)
            if latencies
            else 0.0
        )
        node_latency_breakdown = {
            node_key: (
                round(sum(vals) / len(vals), 2)
                if vals
                else 0.0
            )
            for node_key, vals in node_latencies_collector.items()
        }

        return AnalyticsMetricsResponse(
            total_requests=total_requests,
            status_breakdown=StatusBreakdown(**status_counts),
            decision_breakdown=DecisionBreakdown(**decision_counts),
            auto_approval_rate=auto_approval_rate,
            override_rate=override_rate,
            average_confidence=average_confidence,
            category_breakdown=category_breakdown,
            average_latency_ms=average_latency_ms,
            node_latency_breakdown=node_latency_breakdown,
        )

    def get_analytics_trends(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: Literal["daily", "weekly"] = "daily",
    ) -> AnalyticsTrendsResponse:
        """Compute time-series historical trend analytics bucketed by daily or weekly intervals."""
        table = getattr(self, "_table", self.table)
        response = table.scan()
        raw_items = response.get("Items", []) if isinstance(response, dict) else (response or [])

        filtered_items = _filter_items_by_date_range(raw_items, start_date=start_date, end_date=end_date)

        if not filtered_items:
            return AnalyticsTrendsResponse(
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                points=[],
            )

        buckets: dict[str, dict[str, Any]] = {}

        for item in filtered_items:
            created_at = item.get("created_at")
            if not created_at or not isinstance(created_at, str):
                continue
            created_at_str = created_at.strip()
            if not created_at_str:
                continue

            try:
                clean_ts = created_at_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_ts)
            except Exception:
                try:
                    dt = datetime.strptime(created_at_str[:10], "%Y-%m-%d")
                except Exception:
                    continue

            if interval == "weekly":
                iso_year, iso_week, _ = dt.isocalendar()
                period = f"{iso_year}-W{iso_week:02d}"
            else:
                period = dt.strftime("%Y-%m-%d")

            if period not in buckets:
                buckets[period] = {
                    "total_requests": 0,
                    "auto_approved": 0,
                    "denied": 0,
                    "escalated": 0,
                    "confidence_scores": [],
                    "latencies": [],
                }

            bucket = buckets[period]
            bucket["total_requests"] += 1

            raw_status = str(item.get("status") or "").strip().lower()
            raw_decision = str(item.get("decision") or "").strip().lower()

            if raw_status in ("auto_approved", "auto_approve") or raw_decision in ("auto_approved", "auto_approve"):
                bucket["auto_approved"] += 1
            elif raw_status in ("denied", "deny") or raw_decision in ("denied", "deny"):
                bucket["denied"] += 1
            elif raw_status in ("escalated", "escalate") or raw_decision in ("escalated", "escalate"):
                bucket["escalated"] += 1

            # AI confidence score
            raw_conf = item.get("confidence_score")
            if raw_conf is not None:
                try:
                    bucket["confidence_scores"].append(float(raw_conf))
                except (ValueError, TypeError):
                    pass

            # Latency metrics aggregation
            raw_lat = item.get("latency_ms")
            item_total_latency: float | None = None
            if raw_lat is not None:
                try:
                    item_total_latency = float(raw_lat)
                except (ValueError, TypeError):
                    item_total_latency = None

            raw_nl = item.get("node_latencies")
            if isinstance(raw_nl, dict):
                nl_sum = 0.0
                has_nl_values = False
                for node_key in ("classifier", "policy_checker", "decision_agent"):
                    val = raw_nl.get(node_key)
                    if val is not None:
                        try:
                            f_val = float(val)
                            nl_sum += f_val
                            has_nl_values = True
                        except (ValueError, TypeError):
                            pass
                if item_total_latency is None and has_nl_values:
                    item_total_latency = nl_sum

            if item_total_latency is not None:
                bucket["latencies"].append(item_total_latency)

        points: list[TrendDataPoint] = []
        for period in sorted(buckets.keys()):
            b = buckets[period]
            conf_list = b["confidence_scores"]
            lat_list = b["latencies"]
            avg_conf = round(sum(conf_list) / len(conf_list), 4) if conf_list else 0.0
            avg_lat = round(sum(lat_list) / len(lat_list), 2) if lat_list else 0.0

            points.append(
                TrendDataPoint(
                    period=period,
                    total_requests=b["total_requests"],
                    auto_approved=b["auto_approved"],
                    denied=b["denied"],
                    escalated=b["escalated"],
                    average_confidence=avg_conf,
                    average_latency_ms=avg_lat,
                )
            )

        return AnalyticsTrendsResponse(
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            points=points,
        )

    def get_analytics_category_breakdown(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """Aggregate refund requests by category with decision outcome breakdowns."""
        table = getattr(self, "_table", self.table)
        response = table.scan()
        raw_items = response.get("Items", []) if isinstance(response, dict) else (response or [])

        raw_items = _filter_items_by_date_range(raw_items, start_date=start_date, end_date=end_date)

        categories: dict[str, dict] = {}
        for item in raw_items:
            raw_category = item.get("category")
            if raw_category is not None and str(raw_category).strip():
                cat_key = str(raw_category).strip()
            else:
                cat_key = "unclassified"

            if cat_key not in categories:
                categories[cat_key] = {
                    "category": cat_key,
                    "count": 0,
                    "auto_approved": 0,
                    "escalated": 0,
                    "denied": 0,
                }

            categories[cat_key]["count"] += 1
            raw_decision = str(item.get("decision") or "").strip().lower()
            if raw_decision == "auto_approve":
                categories[cat_key]["auto_approved"] += 1
            elif raw_decision == "escalate":
                categories[cat_key]["escalated"] += 1
            elif raw_decision == "deny":
                categories[cat_key]["denied"] += 1

        return sorted(categories.values(), key=lambda x: x["category"])




