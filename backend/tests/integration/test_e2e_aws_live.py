"""Live AWS integration tests for Bedrock and DynamoDB integration.

These tests execute against live AWS resources when valid credentials and tables
are available in the environment. Marked with @pytest.mark.aws to isolate from
fast offline unit/integration suites.
"""

import os
from typing import Any
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
import pytest

from app.agents.classifier import classify_refund_request
from app.agents.llm import get_bedrock_llm
from app.agents.policy_checker import check_policy
from app.core.config import get_settings
from app.db.repository import RefundRepository
from app.graph.runner import run_refund_workflow


def _has_aws_credentials() -> bool:
    """Check if environment has AWS credentials configured."""
    settings = get_settings()
    if settings.aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"):
        return True
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None and credentials.access_key is not None
    except Exception:
        return False


@pytest.mark.aws
def test_bedrock_live_model_invocation():
    """Verify live Bedrock model invocation using the configured model ID."""
    if not _has_aws_credentials():
        pytest.skip("AWS credentials not configured in environment.")

    settings = get_settings()
    llm = get_bedrock_llm()
    try:
        response = llm.invoke("Hello, answer with 'ok' to verify connectivity.")
        assert response is not None
        assert len(response.content) > 0
    except (NoCredentialsError, EndpointConnectionError) as exc:
        pytest.skip(f"AWS Bedrock connection failed: {exc}")
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        if error_code in ("AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException"):
            pytest.skip(f"AWS Bedrock access denied or expired token: {exc}")
        raise


@pytest.mark.aws
def test_bedrock_live_classifier_structured_output():
    """Verify live Bedrock model produces structured ClassificationOutput."""
    if not _has_aws_credentials():
        pytest.skip("AWS credentials not configured in environment.")

    try:
        output = classify_refund_request("The chair armrest arrived completely broken and cracked.")
        assert output is not None
        assert output.category == "damaged"
        assert output.confidence_score >= 0.7
        assert len(output.reasoning) > 0
    except (NoCredentialsError, EndpointConnectionError) as exc:
        pytest.skip(f"AWS Bedrock connection failed: {exc}")
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        pytest.skip(f"AWS Bedrock client error during live classification: {exc}")


@pytest.mark.aws
@pytest.mark.asyncio
async def test_live_aws_full_workflow_execution():
    """Verify full LangGraph workflow execution against live AWS Bedrock and DynamoDB."""
    if not _has_aws_credentials():
        pytest.skip("AWS credentials not configured in environment.")

    settings = get_settings()
    # Check if DynamoDB table exists
    dynamodb_kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        dynamodb_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        dynamodb_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            dynamodb_kwargs["aws_session_token"] = settings.aws_session_token
    if settings.dynamodb_endpoint_url:
        dynamodb_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url

    dynamodb = boto3.resource("dynamodb", **dynamodb_kwargs)
    table = dynamodb.Table(settings.dynamodb_table_refunds)
    try:
        table.load()
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        pytest.skip(
            f"Live DynamoDB table '{settings.dynamodb_table_refunds}' not accessible or not provisioned: {exc}"
        )
    except Exception as exc:
        pytest.skip(f"Live DynamoDB connection failed: {exc}")

    repo = RefundRepository(
        dynamodb_resource=dynamodb, table_name=settings.dynamodb_table_refunds
    )

    try:
        # Create initial record in live DynamoDB with non-damage category to verify direct completion
        record = repo.create_refund_request(
            order_id="ORD-1001",
            customer_request_text="I changed my mind and no longer need this chair.",
        )
        assert record.refund_id is not None

        # Execute full workflow with live Bedrock
        final_state = await run_refund_workflow(
            refund_id=record.refund_id,
            order_id="ORD-1001",
            customer_request_text=record.customer_request_text,
            repository=repo,
        )

        assert final_state["status"] in ("completed", "escalated")
        assert final_state["decision"] in ("auto_approve", "deny", "escalate")

        # Verify record updated in live DynamoDB
        updated = repo.get_refund_request(record.refund_id)
        assert updated is not None
        assert updated.decision == final_state["decision"]
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        pytest.skip(f"Live AWS operation skipped due to ClientError: {exc}")


@pytest.mark.aws
@pytest.mark.asyncio
async def test_live_aws_damaged_without_evidence_pauses_for_clarification():
    """Verify live workflow for damaged claim without evidence pauses at awaiting_clarification."""
    if not _has_aws_credentials():
        pytest.skip("AWS credentials not configured in environment.")

    settings = get_settings()
    dynamodb_kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        dynamodb_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        dynamodb_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            dynamodb_kwargs["aws_session_token"] = settings.aws_session_token
    if settings.dynamodb_endpoint_url:
        dynamodb_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url

    dynamodb = boto3.resource("dynamodb", **dynamodb_kwargs)
    table = dynamodb.Table(settings.dynamodb_table_refunds)
    try:
        table.load()
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        pytest.skip(f"Live DynamoDB table not accessible: {exc}")
    except Exception as exc:
        pytest.skip(f"Live DynamoDB connection failed: {exc}")

    repo = RefundRepository(
        dynamodb_resource=dynamodb, table_name=settings.dynamodb_table_refunds
    )

    try:
        record = repo.create_refund_request(
            order_id="ORD-1001",
            customer_request_text="Chair arrived with shattered plastic frame during delivery.",
        )
        assert record.refund_id is not None

        final_state = await run_refund_workflow(
            refund_id=record.refund_id,
            order_id="ORD-1001",
            customer_request_text=record.customer_request_text,
            repository=repo,
        )

        assert final_state["status"] == "awaiting_clarification"
        assert final_state.get("clarification_prompt") is not None
        assert final_state.get("clarification_count") == 1

        updated = repo.get_refund_request(record.refund_id)
        assert updated is not None
        assert updated.status == "awaiting_clarification"
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        pytest.skip(f"Live AWS operation skipped due to ClientError: {exc}")


@pytest.mark.aws
def test_bedrock_live_policy_checker_reasoning_tool_loop():
    """Verify live Bedrock Nova 2 model executes tool loop and structured extraction with reasoningConfig."""
    if not _has_aws_credentials():
        pytest.skip("AWS credentials not configured in environment.")

    settings = get_settings().model_copy(
        update={
            "bedrock_model_id": "us.amazon.nova-2-lite-v1:0",
            "bedrock_thinking_effort": "high",
        }
    )
    llm = get_bedrock_llm(settings=settings)

    order = {
        "order_id": "ORD-1005",
        "item": "Standing Desk Converter",
        "delivery_status": "in_transit",
    }
    try:
        output = check_policy(category="late_delivery", order=order, llm=llm)
        assert output is not None
        assert output.policy_status in ("pass", "fail", "ambiguous")
        assert len(output.policy_reasoning) > 0
        assert len(output.tool_calls) > 0
        assert any(t.get("tool_name") == "query_carrier_tracking" for t in output.tool_calls)
    except (NoCredentialsError, EndpointConnectionError) as exc:
        pytest.skip(f"AWS Bedrock connection failed: {exc}")
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        if error_code in ("AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException"):
            pytest.skip(f"AWS Bedrock access denied or expired token: {exc}")
        raise

