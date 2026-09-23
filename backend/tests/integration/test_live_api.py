"""Live HTTP API integration tests for unmocked FastAPI endpoints.

Exercises health, submission, polling, queue listing, and manual override endpoints
against live DynamoDB tables and unmocked application state without dependency overrides.
Marked with @pytest.mark.aws to isolate from fast offline test suites.
"""

import asyncio
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
from httpx import ASGITransport, AsyncClient
import pytest

from app.core.config import Settings, get_settings
from app.db.repository import RefundRepository
from app.db.seed import seed_orders
from app.main import app

pytestmark = pytest.mark.aws


def check_live_aws_and_dynamodb() -> None:
    """Verify active AWS credentials and reachability of live DynamoDB tables.

    Skips tests via pytest.skip if credentials or tables are inaccessible.
    """
    settings: Settings = get_settings()

    # 1. Check AWS credentials across settings, environment, or boto3 session
    has_creds = False
    if settings.aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID"):
        has_creds = True
    else:
        try:
            session = boto3.Session()
            creds = session.get_credentials()
            if creds is not None and creds.access_key:
                has_creds = True
        except Exception:
            pass

    if not has_creds:
        pytest.skip("AWS credentials not configured in environment or settings.")

    # 2. Check DynamoDB table connectivity to refunds table
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url

    try:
        dynamodb = boto3.resource("dynamodb", **kwargs)
        refunds_table = dynamodb.Table(settings.dynamodb_table_refunds)
        refunds_table.load()
    except (NoCredentialsError, EndpointConnectionError) as exc:
        pytest.skip(f"Live AWS DynamoDB connection failed: {exc}")
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        pytest.skip(
            f"Live DynamoDB table '{settings.dynamodb_table_refunds}' not accessible ({error_code}): {exc}"
        )
    except Exception as exc:
        pytest.skip(f"Live DynamoDB connection failed: {exc}")

    # 3. Seed orders if needed so ORD-1001 exists in DynamoDB
    try:
        orders_table = dynamodb.Table(settings.dynamodb_table_orders)
        orders_table.load()
        resp = orders_table.get_item(Key={"order_id": "ORD-1001"})
        if "Item" not in resp:
            seed_orders(
                table_name=settings.dynamodb_table_orders,
                dynamodb_resource=dynamodb,
                settings=settings,
            )
    except Exception:
        # Fallback to local mock_orders.json is supported gracefully in workflow
        pass


@pytest.fixture(autouse=True, scope="module")
def ensure_aws_environment():
    """Module-level fixture ensuring live AWS and DynamoDB availability."""
    check_live_aws_and_dynamodb()


@pytest.mark.asyncio
async def test_live_health_endpoint():
    """Verify GET /health returns HTTP 200 with healthy status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "healthy"} or data.get("status") in ("healthy", "ok")


@pytest.mark.asyncio
async def test_live_submit_and_poll_refund():
    """Verify POST /refunds initiates processing and GET /refunds/{id} completes."""
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            post_response = await client.post(
                "/refunds",
                json={
                    "order_id": "ORD-1001",
                    "customer_request_text": "The chair armrest arrived completely broken and cracked during delivery.",
                },
            )
            assert post_response.status_code == 202
            post_data = post_response.json()
            refund_id = post_data["refund_id"]
            assert refund_id
            assert post_data["order_id"] == "ORD-1001"
            assert post_data["status"] == "pending"

            # Poll GET /refunds/{refund_id} until status is not "pending" (up to 30s)
            max_wait = 30.0
            poll_interval = 1.0
            elapsed = 0.0
            refund_record = None

            while elapsed < max_wait:
                get_response = await client.get(f"/refunds/{refund_id}")
                assert get_response.status_code == 200
                refund_record = get_response.json()
                if refund_record.get("status") in ("completed", "escalated"):
                    break
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

        assert refund_record is not None, "Failed to retrieve refund record"
        assert refund_record["status"] in ("completed", "escalated")
        assert refund_record["decision"] in ("auto_approve", "deny", "escalate")
        assert bool(refund_record.get("reasoning"))

        # Verify persisted in live DynamoDB directly
        repo = RefundRepository()
        db_record = repo.get_refund_request(refund_id)
        assert db_record is not None
        assert db_record.status == refund_record["status"]
        assert db_record.decision == refund_record["decision"]
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationException":
            raise
        pytest.skip(f"Live AWS Bedrock operation skipped due to ClientError: {exc}")


@pytest.mark.asyncio
async def test_live_list_refund_queue():
    """Verify GET /refunds returns queue records and filters by status."""
    repo = RefundRepository()
    record = repo.create_refund_request(
        order_id="ORD-1001",
        customer_request_text="Queue listing verification request.",
    )
    repo.apply_override(
        refund_id=record.refund_id,
        override_decision="approve",
        override_reason="Live queue listing verification",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unfiltered queue listing
        list_response = await client.get("/refunds")
        assert list_response.status_code == 200
        items = list_response.json()
        assert isinstance(items, list)
        assert len(items) > 0

        # 2. Filtered queue listing by status=completed
        completed_response = await client.get("/refunds?status=completed")
        assert completed_response.status_code == 200
        completed_items = completed_response.json()
        assert isinstance(completed_items, list)
        assert len(completed_items) > 0
        assert all(item["status"] == "completed" for item in completed_items)
        assert any(item["refund_id"] == record.refund_id for item in completed_items)


@pytest.mark.asyncio
async def test_live_manual_override():
    """Verify POST /refunds/{refund_id}/override updates decision and override reason in DynamoDB."""
    repo = RefundRepository()
    record = repo.create_refund_request(
        order_id="ORD-1001",
        customer_request_text="Customer requested supervisor review for chair damage.",
    )
    refund_id = record.refund_id

    transport = ASGITransport(app=app)
    override_payload = {
        "override_decision": "approve",
        "reason": "Operator discretion approval",
        "override_reason": "Operator discretion approval",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/refunds/{refund_id}/override",
            json=override_payload,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["refund_id"] == refund_id
    assert data["decision"] == "approve"
    assert data["override_decision"] == "approve"
    assert data["override_reason"] == "Operator discretion approval"
    assert data["status"] == "completed"
    assert data["overridden_at"] is not None

    # Verify persisted in live DynamoDB directly
    updated_record = repo.get_refund_request(refund_id)
    assert updated_record is not None
    assert updated_record.decision == "approve"
    assert updated_record.override_decision == "approve"
    assert updated_record.override_reason == "Operator discretion approval"
    assert updated_record.status == "completed"


@pytest.mark.asyncio
async def test_live_override_nonexistent_returns_404():
    """Verify POST /refunds/{nonexistent_id}/override returns HTTP 404."""
    transport = ASGITransport(app=app)
    override_payload = {
        "override_decision": "approve",
        "reason": "Operator discretion approval",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/refunds/nonexistent_id_9999/override",
            json=override_payload,
        )

    assert response.status_code == 404
    assert "not found" in response.json().get("detail", "").lower()
