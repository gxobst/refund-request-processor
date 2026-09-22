"""Live AWS integration tests for Bedrock and DynamoDB integration.

These tests execute against live AWS resources when valid credentials and tables
are available in the environment. Marked with @pytest.mark.aws to isolate from
fast offline unit/integration suites.
"""

import os
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
import pytest

from app.agents.classifier import classify_refund_request
from app.agents.llm import get_bedrock_llm
from app.core.config import get_settings
from app.db.repository import RefundRepository
from app.graph.runner import run_refund_workflow


def _has_aws_credentials() -> bool:
    """Check if environment has AWS credentials configured."""
    if os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"):
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
        pytest.skip(f"AWS Bedrock client error during live classification: {exc}")


@pytest.mark.aws
@pytest.mark.asyncio
async def test_live_aws_full_workflow_execution():
    """Verify full LangGraph workflow execution against live AWS Bedrock and DynamoDB."""
    if not _has_aws_credentials():
        pytest.skip("AWS credentials not configured in environment.")

    settings = get_settings()
    # Check if DynamoDB table exists
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = dynamodb.Table(settings.dynamodb_table_refunds)
    try:
        table.load()
    except ClientError as exc:
        pytest.skip(
            f"Live DynamoDB table '{settings.dynamodb_table_refunds}' not accessible or not provisioned: {exc}"
        )
    except Exception as exc:
        pytest.skip(f"Live DynamoDB connection failed: {exc}")

    repo = RefundRepository(
        dynamodb_resource=dynamodb, table_name=settings.dynamodb_table_refunds
    )

    try:
        # Create initial record in live DynamoDB
        record = repo.create_refund_request(
            order_id="ORD-1001",
            customer_request_text="Chair arrived with shattered plastic frame during delivery.",
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
        pytest.skip(f"Live AWS operation skipped due to ClientError: {exc}")
