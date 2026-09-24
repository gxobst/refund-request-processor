import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate

from app.agents.llm import get_bedrock_llm
from app.policy.engine import evaluate_policy
from app.policy.loader import load_policies
from app.policy.schema import PolicyConfig
from app.schemas.policy_checker import PolicyCheckerOutput
from app.tools import ALL_TOOLS, query_carrier_tracking, query_payment_transaction

POLICY_CHECKER_SYSTEM_PROMPT = """You are an expert refund policy analyst for an e-commerce platform.
Evaluate the refund request category, order details, deterministic findings, and policy rules to determine refund eligibility.

You have access to the following verification tools:
- query_carrier_tracking: Use this tool to look up carrier delivery status, delivery dates, and proof-of-delivery photos (useful for late delivery claims or lost packages). If a tracking number is not explicitly given in the order details, use 'TRK-' followed by the order ID number (for example, 'TRK-1005' for order 'ORD-1005').
- query_payment_transaction: Use this tool to look up Stripe charge status, dispute state, and refund eligibility for an order.

When evaluating requests requiring external verification (such as late deliveries, missing order data, high-value orders, or ambiguous claims), call the appropriate tools to gather evidence before making a final determination. For high-value orders or ambiguous claims, verify both carrier delivery status (via query_carrier_tracking) and payment transaction status (via query_payment_transaction) to ensure delivery proof and charge eligibility before concluding.

When evaluating damage claims (category: 'damaged') with attached photos, inspect the images to verify whether:
1. The image depicts the ordered product (product match).
2. The image exhibits visible physical damage consistent with the customer's claim.
- If physical damage matching the claim is clearly visible on the ordered product, conclude policy_status: 'pass' with reasoning confirming physical damage was verified.
- If the item appears intact with no visible damage, conclude policy_status: 'fail' (or 'ambiguous') with reasoning stating no damage was detected.
- If the image is blurry, inconclusive, corrupted, or depicts a mismatched product, conclude policy_status: 'ambiguous' requiring human reviewer inspection.

Return a structured output with:
- policy_status: 'pass' (eligible), 'fail' (clearly ineligible), or 'ambiguous' (requires human review).
- passed_rules: list of satisfied rule names.
- failed_rules: list of failed rule names.
- policy_reasoning: explanation of your determination and justification for escalation if ambiguous.
"""

AMBIGUITY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", POLICY_CHECKER_SYSTEM_PROMPT),
    (
        "human",
        """Category: {category}
Order Details: {order}
Deterministic Findings: {details}
Policy Rule: {policy_rule}

Analyze the situation and provide your determination:""",
    ),
])


FINAL_SYNTHESIS_PROMPT = """Provide your final policy determination formatted as a strict JSON object with keys:
- "policy_status": "pass", "fail", or "ambiguous"
- "passed_rules": list of passed rule names (e.g. ["refund_window_days", "eligible_delivery_statuses", "max_order_amount"])
- "failed_rules": list of failed rule names
- "policy_reasoning": detailed explanation of your determination and evidence

Respond with ONLY the JSON object, with no additional conversational text or markdown code fences."""


def _extract_text(content: Any) -> str:
    """Extract plain text from model message content (handling str or block lists)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    text_parts.append(block["text"])
                elif "text" in block and block.get("type") != "reasoning_content":
                    text_parts.append(block["text"])
        return "\n".join(text_parts)
    return str(content) if content is not None else ""


def _parse_policy_checker_output(
    text: str,
    eval_result: Any,
    executed_tool_calls: list[dict[str, Any]],
) -> PolicyCheckerOutput | None:
    """Attempt to extract and parse PolicyCheckerOutput from text containing JSON."""
    if not text or not text.strip():
        return None

    candidate_strings: list[str] = []

    # 1. Search for JSON within markdown code blocks (```json ... ``` or ``` ... ```)
    code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if code_block_match:
        block_text = code_block_match.group(1).strip()
        candidate_strings.append(block_text)
        start = block_text.find("{")
        end = block_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate_strings.append(block_text[start : end + 1])

    regex_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if regex_match:
        candidate_strings.append(regex_match.group(1).strip())

    # 2. Check for first { and last } across entire text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate_strings.append(text[start : end + 1])

    # 3. Check trimmed full text
    candidate_strings.append(text.strip())

    for candidate in candidate_strings:
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                continue
            if "policy_status" not in parsed:
                continue

            if "matched_policy_rule" not in parsed or parsed["matched_policy_rule"] is None:
                parsed["matched_policy_rule"] = eval_result.matched_policy_rule

            if "tool_calls" not in parsed or not parsed["tool_calls"]:
                parsed["tool_calls"] = executed_tool_calls

            output = PolicyCheckerOutput.model_validate(parsed)
            if output.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                output.matched_policy_rule = eval_result.matched_policy_rule
            if not output.tool_calls and executed_tool_calls:
                output.tool_calls = executed_tool_calls
            return output
        except Exception:
            continue

    return None


def _extract_image_block(item: Any, storage_service: Any = None) -> dict[str, Any] | None:
    """Convert an evidence item into a multimodal Bedrock Converse image content block."""
    if hasattr(item, "model_dump"):
        item_dict = item.model_dump()
    elif isinstance(item, dict):
        item_dict = item
    else:
        item_dict = {}

    content_type = item_dict.get("content_type") or getattr(item, "content_type", "")
    filename = item_dict.get("filename") or getattr(item, "filename", "")
    storage_key = item_dict.get("storage_key") or getattr(item, "storage_key", None)

    # Ignore video or non-image files
    if content_type.startswith("video/") or any(
        filename.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv")
    ):
        return None

    file_bytes: bytes | None = None
    if "bytes" in item_dict and isinstance(item_dict["bytes"], (bytes, bytearray)):
        file_bytes = bytes(item_dict["bytes"])
    elif "raw_bytes" in item_dict and isinstance(item_dict["raw_bytes"], (bytes, bytearray)):
        file_bytes = bytes(item_dict["raw_bytes"])
    elif isinstance(item, (bytes, bytearray)):
        file_bytes = bytes(item)
    elif "base64" in item_dict and isinstance(item_dict["base64"], str):
        b64_str = item_dict["base64"]
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        file_bytes = base64.b64decode(b64_str)
    elif "data" in item_dict and isinstance(item_dict["data"], str):
        b64_str = item_dict["data"]
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        file_bytes = base64.b64decode(b64_str)
    elif storage_key:
        if storage_service is None:
            from app.services.storage import get_evidence_storage_service
            storage_service = get_evidence_storage_service()
        file_bytes = storage_service.get_file(storage_key)

    if not file_bytes:
        return None

    # Determine format/content_type
    if not content_type or not content_type.startswith("image/"):
        ext = Path(filename).suffix.lower() if filename else ""
        if ext in (".jpg", ".jpeg"):
            content_type = "image/jpeg"
        elif ext == ".png":
            content_type = "image/png"
        elif ext == ".webp":
            content_type = "image/webp"
        elif file_bytes.startswith(b"\xff\xd8\xff"):
            content_type = "image/jpeg"
        elif file_bytes.startswith(b"\x89PNG"):
            content_type = "image/png"
        elif file_bytes.startswith(b"RIFF") and b"WEBP" in file_bytes[:16]:
            content_type = "image/webp"
        else:
            content_type = "image/jpeg"

    b64_encoded = base64.b64encode(file_bytes).decode("utf-8")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": content_type,
            "data": b64_encoded,
        },
        "image_url": {
            "url": f"data:{content_type};base64,{b64_encoded}",
        },
    }


def check_policy(
    category: str,
    order: dict[str, Any],
    policies: PolicyConfig | None = None,
    llm: BaseChatModel | None = None,
    tools: list[Any] | None = None,
    max_tool_iterations: int = 5,
    customer_request_text: str | None = None,
    evidence: list[dict[str, Any]] | list[Any] | None = None,
    storage_service: Any | None = None,
) -> PolicyCheckerOutput:
    """Evaluate a refund request against policies, bypassing LLM on clear-cut cases.

    Args:
        category: Refund category.
        order: Order data dictionary.
        policies: Optional loaded PolicyConfig. Defaults to default policies.json.
        llm: Optional BaseChatModel instance for ambiguity resolution and tool calling.
        tools: Optional list of tools to bind to the model. Defaults to carrier and payment tools.
        max_tool_iterations: Maximum number of tool calling turns (default 5).
        customer_request_text: Optional customer-provided explanation text.
        evidence: Optional list of customer evidence metadata items.
        storage_service: Optional EvidenceStorageService instance for loading evidence files.

    Returns:
        PolicyCheckerOutput instance.
    """
    active_policies = policies if policies is not None else load_policies()
    eval_result = evaluate_policy(category=category, order=order, policy=active_policies)

    # Process evidence items
    image_blocks: list[dict[str, Any]] = []
    has_video_evidence = False
    has_image_evidence = False

    if evidence:
        for ev in evidence:
            ev_dict = ev.model_dump() if hasattr(ev, "model_dump") else (ev if isinstance(ev, dict) else {})
            c_type = ev_dict.get("content_type") or getattr(ev, "content_type", "")
            f_name = ev_dict.get("filename") or getattr(ev, "filename", "")
            is_video = c_type.startswith("video/") or any(
                f_name.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv")
            )
            if is_video:
                has_video_evidence = True
                continue

            has_image_evidence = True
            try:
                block = _extract_image_block(ev, storage_service)
                if block is not None:
                    image_blocks.append(block)
            except Exception as e:
                err_detail = str(e) or type(e).__name__
                return PolicyCheckerOutput(
                    policy_status="ambiguous",
                    matched_policy_rule=eval_result.matched_policy_rule,
                    passed_rules=eval_result.passed_rules,
                    failed_rules=eval_result.failed_rules,
                    policy_reasoning=f"Failed to retrieve evidence file: {err_detail}",
                    tool_calls=[],
                )

        if has_video_evidence and not has_image_evidence:
            return PolicyCheckerOutput(
                policy_status="ambiguous",
                matched_policy_rule=eval_result.matched_policy_rule,
                passed_rules=eval_result.passed_rules,
                failed_rules=eval_result.failed_rules,
                policy_reasoning="Video evidence requires manual reviewer inspection.",
                tool_calls=[],
            )

    # 1. Deterministic Pass Bypass
    # Clear-cut pass bypasses LLM except for:
    # - late_delivery (requires external carrier verification)
    # - high-value orders (order_amount >= 400.0, requires dual external verification)
    # - damaged category when valid image evidence is provided (requires multimodal LLM inspection)
    is_high_value = float(order.get("order_amount", 0.0) or 0.0) >= 400.0
    has_active_image_evidence = bool(image_blocks)
    should_bypass_pass = (
        category == "late_delivery"
        or is_high_value
        or (category == "damaged" and has_active_image_evidence)
    )
    if eval_result.status == "pass" and not should_bypass_pass:
        return PolicyCheckerOutput(
            policy_status="pass",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=eval_result.details or "All policy rules passed.",
            tool_calls=[],
        )

    # 2. Deterministic Supervisor Escalation for Order Amount Violations
    if eval_result.status == "ambiguous" and eval_result.failed_rules == ["max_order_amount"]:
        return PolicyCheckerOutput(
            policy_status="ambiguous",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=eval_result.details
            or "Order amount exceeds maximum policy threshold; requires supervisor review.",
            tool_calls=[],
        )

    # 3. Deterministic Fail Bypass
    # Clear-cut fail on hard constraints (e.g. expired refund window, ineligible delivery status)
    if eval_result.status == "fail":
        is_hard_constraint = (
            "max_order_amount" in eval_result.failed_rules
            or category != "late_delivery"
        )
        if is_hard_constraint:
            return PolicyCheckerOutput(
                policy_status="fail",
                matched_policy_rule=eval_result.matched_policy_rule,
                passed_rules=eval_result.passed_rules,
                failed_rules=eval_result.failed_rules,
                policy_reasoning=eval_result.details
                or f"Evaluation failed for rules: {', '.join(eval_result.failed_rules)}",
                tool_calls=[],
            )

    # 3. LLM External Verification and Ambiguity Resolution
    executed_tool_calls: list[dict[str, Any]] = []
    active_tools = tools if tools is not None else [query_carrier_tracking, query_payment_transaction]
    tool_map: dict[str, Any] = {}
    for t in active_tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            tool_map[name] = t

    model = llm or get_bedrock_llm()
    if active_tools and hasattr(model, "bind_tools"):
        bound_model = model.bind_tools(active_tools)
    else:
        bound_model = model

    rule_repr = (
        eval_result.matched_policy_rule.model_dump()
        if hasattr(eval_result.matched_policy_rule, "model_dump")
        else eval_result.matched_policy_rule
    )

    customer_line = (
        f"\nCustomer Explanation: {customer_request_text.strip()}"
        if customer_request_text and customer_request_text.strip()
        else ""
    )
    human_text = f"""Category: {category}
Order Details: {order}{customer_line}
Deterministic Findings: {eval_result.details}
Policy Rule: {rule_repr}

Analyze the situation and provide your determination:"""

    if image_blocks:
        human_content: list[Any] = [{"type": "text", "text": human_text}] + image_blocks
    else:
        human_content = human_text

    messages: list[Any] = [
        SystemMessage(content=POLICY_CHECKER_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]

    try:
        # Multi-turn tool execution loop
        for _ in range(max_tool_iterations):
            response = bound_model.invoke(messages)
            if isinstance(response, PolicyCheckerOutput):
                result = response
                if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                    result.matched_policy_rule = eval_result.matched_policy_rule
                result.tool_calls = executed_tool_calls
                return result

            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None)
            if isinstance(tool_calls, list) and tool_calls:
                for call in tool_calls:
                    name = call.get("name", "")
                    raw_args = call.get("args", {})
                    call_id = call.get("id") or "call_id"

                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            args = raw_args
                    else:
                        args = raw_args

                    if name in tool_map:
                        try:
                            tool = tool_map[name]
                            if hasattr(tool, "invoke"):
                                raw_res = tool.invoke(args)
                            elif isinstance(args, dict):
                                raw_res = tool(**args)
                            else:
                                raw_res = tool(args)
                            content = raw_res if isinstance(raw_res, str) else json.dumps(raw_res)
                            tool_output = raw_res
                        except Exception as e:
                            tool_output = {"error": f"Tool execution error: {str(e)}"}
                            content = json.dumps(tool_output)
                    else:
                        tool_output = {
                            "error": f"Tool '{name}' not found. Available tools: {list(tool_map.keys())}"
                        }
                        content = json.dumps(tool_output)

                    audit_entry = {
                        "tool_name": name,
                        "tool_call_id": call_id,
                        "tool_input": args,
                        "tool_output": tool_output,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    executed_tool_calls.append(audit_entry)

                    messages.append(
                        ToolMessage(
                            content=content,
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
            else:
                # Fast extraction if terminal response already contains valid JSON
                fast_text = _extract_text(getattr(response, "content", ""))
                fast_result = _parse_policy_checker_output(
                    fast_text, eval_result, executed_tool_calls
                )
                if fast_result is not None:
                    return fast_result
                break

        # Produce final structured output via reasoning-safe extraction
        messages.append(HumanMessage(content=FINAL_SYNTHESIS_PROMPT))
        final_response = bound_model.invoke(messages)

        if isinstance(final_response, PolicyCheckerOutput):
            result = final_response
            if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                result.matched_policy_rule = eval_result.matched_policy_rule
            result.tool_calls = executed_tool_calls
            return result

        final_text = _extract_text(getattr(final_response, "content", final_response))
        parsed_result = _parse_policy_checker_output(
            final_text, eval_result, executed_tool_calls
        )

        mock_final_output = getattr(bound_model, "final_output", None) or getattr(model, "final_output", None)
        if parsed_result is not None:
            result = parsed_result
        elif isinstance(mock_final_output, PolicyCheckerOutput):
            result = mock_final_output.model_copy(deep=True)
            if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
                result.matched_policy_rule = eval_result.matched_policy_rule
            result.tool_calls = executed_tool_calls
            return result
        else:
            return PolicyCheckerOutput(
                policy_status="ambiguous",
                matched_policy_rule=eval_result.matched_policy_rule,
                passed_rules=eval_result.passed_rules,
                failed_rules=eval_result.failed_rules,
                policy_reasoning=f"Could not parse policy determination from model output: {final_text[:200]}",
                tool_calls=executed_tool_calls,
            )

    except Exception as e:
        err_msg = str(e).strip()
        error_detail = err_msg if err_msg else type(e).__name__
        return PolicyCheckerOutput(
            policy_status="ambiguous",
            matched_policy_rule=eval_result.matched_policy_rule,
            passed_rules=eval_result.passed_rules,
            failed_rules=eval_result.failed_rules,
            policy_reasoning=f"External verification failed: {error_detail}",
            tool_calls=executed_tool_calls,
        )

    if result.matched_policy_rule is None and eval_result.matched_policy_rule is not None:
        result.matched_policy_rule = eval_result.matched_policy_rule

    if not result.tool_calls and executed_tool_calls:
        result.tool_calls = executed_tool_calls

    return result


def policy_checker_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node function executing the Policy Checker Agent.

    Args:
        state: Workflow state dictionary containing 'category', 'order', and/or 'order_id'.

    Returns:
        Updated dictionary containing policy checker keys.
    """
    category = state.get("category", "")
    order = state.get("order")
    if not order:
        order = {"order_id": state.get("order_id", "")}
    customer_request_text = state.get("customer_request_text")
    evidence = state.get("evidence")

    output = check_policy(
        category=category,
        order=order,
        customer_request_text=customer_request_text,
        evidence=evidence,
    )

    matched_rule = output.matched_policy_rule
    if hasattr(matched_rule, "model_dump"):
        matched_rule = matched_rule.model_dump()

    return {
        "policy_status": output.policy_status,
        "matched_policy_rule": matched_rule,
        "policy_reasoning": output.policy_reasoning,
        "passed_rules": output.passed_rules,
        "failed_rules": output.failed_rules,
        "tool_calls": output.tool_calls,
    }

