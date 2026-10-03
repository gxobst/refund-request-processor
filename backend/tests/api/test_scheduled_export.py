"""Unit and integration tests for recurring queue export schedule endpoints and email delivery."""

from datetime import datetime, timezone
from email import message_from_bytes
import io
import json
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.refunds import (
    get_export_schedules_store,
    get_repository,
    reset_export_schedules,
)
from app.core.config import Settings
from app.main import app
from app.schemas.refund import RefundRecord
from app.services.email_delivery import (
    build_export_report_email,
    clear_delivered_emails,
    get_delivered_emails,
    send_export_report_email,
)


class MockRefundRepository:
    """In-memory mock repository for scheduled export testing."""

    def __init__(self) -> None:
        self.records: dict[str, RefundRecord] = {}

    def seed_record(
        self,
        refund_id: str,
        order_id: str,
        status: str,
        order_amount: float = 99.99,
        customer_request_text: str | None = None,
        created_at: str | None = None,
    ) -> RefundRecord:
        now_iso = created_at or datetime.now(timezone.utc).isoformat()
        record = RefundRecord(
            refund_id=refund_id,
            order_id=order_id,
            customer_request_text=customer_request_text or f"Refund requested for {order_id}",
            status=status,
            order_amount=order_amount,
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.records[refund_id] = record
        return record

    def list_refund_requests(
        self, status: str | None = None, limit: int = 10000
    ) -> list[RefundRecord]:
        records = list(self.records.values())
        if status is not None:
            records = [r for r in records if r.status.lower() == status.strip().lower()]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]


@pytest.fixture(autouse=True)
def clean_state():
    reset_export_schedules()
    clear_delivered_emails()
    yield
    reset_export_schedules()
    clear_delivered_emails()


@pytest.fixture
def mock_repo() -> MockRefundRepository:
    repo = MockRefundRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_repository, None)


def test_settings_ses_sender_email_default():
    """Verify default ses_sender_email setting is noreply@refunds.example.com."""
    s = Settings()
    assert s.ses_sender_email == "noreply@refunds.example.com"


@pytest.mark.asyncio
async def test_create_export_schedule_success():
    """Verify POST /v1/refunds/export/schedules creates schedule returning 201."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "name": "Daily Completed Refunds",
            "recipients": ["manager@example.com", "finance@example.com"],
            "frequency": "daily",
            "format": "csv",
            "status_filter": "completed",
            "columns": ["Refund ID", "Order ID", "Status", "Refund Amount"],
            "enabled": True,
        }
        res = await client.post("/v1/refunds/export/schedules", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["schedule_id"].startswith("sch_")
        assert data["name"] == "Daily Completed Refunds"
        assert len(data["recipients"]) == 2
        assert data["frequency"] == "daily"
        assert data["format"] == "csv"
        assert data["status_filter"] == "completed"
        assert "refund_id" in data["columns"]
        assert data["enabled"] is True
        assert data["last_status"] == "never_run"
        assert data["last_run"] is None
        assert "created_at" in data

        # Also test non-v1 path
        payload2 = {
            "name": "Weekly Pending Refunds",
            "recipients": ["ops@example.com"],
            "frequency": "weekly",
            "format": "json",
        }
        res2 = await client.post("/refunds/export/schedules", json=payload2)
        assert res2.status_code == 201
        assert res2.json()["schedule_id"].startswith("sch_")


@pytest.mark.asyncio
async def test_create_export_schedule_validation_errors():
    """Verify 422 when recipients is empty, invalid email, or blank name."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Empty recipients
        res = await client.post(
            "/v1/refunds/export/schedules",
            json={"name": "Test", "recipients": []},
        )
        assert res.status_code == 422

        # Invalid email syntax
        res = await client.post(
            "/v1/refunds/export/schedules",
            json={"name": "Test", "recipients": ["invalid-email-address"]},
        )
        assert res.status_code == 422

        # Blank name
        res = await client.post(
            "/v1/refunds/export/schedules",
            json={"name": "   ", "recipients": ["valid@example.com"]},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_export_schedule_invalid_column():
    """Verify 400 Bad Request ProblemDetails when invalid column name is specified."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "name": "Custom Columns",
            "recipients": ["admin@example.com"],
            "columns": ["Refund ID", "nonexistent_column_field"],
        }
        res = await client.post("/v1/refunds/export/schedules", json=payload)
        assert res.status_code == 400
        problem = res.json()
        assert problem["type"] == "urn:problem:bad-request"
        assert "nonexistent_column_field" in problem["detail"]


@pytest.mark.asyncio
async def test_list_and_get_export_schedules():
    """Verify listing and retrieving individual export schedules."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create 2 schedules
        s1 = (
            await client.post(
                "/v1/refunds/export/schedules",
                json={"name": "Schedule 1", "recipients": ["s1@example.com"]},
            )
        ).json()
        s2 = (
            await client.post(
                "/v1/refunds/export/schedules",
                json={"name": "Schedule 2", "recipients": ["s2@example.com"]},
            )
        ).json()

        # List schedules
        list_res = await client.get("/v1/refunds/export/schedules")
        assert list_res.status_code == 200
        items = list_res.json()
        assert len(items) == 2
        ids = [i["schedule_id"] for i in items]
        assert s1["schedule_id"] in ids
        assert s2["schedule_id"] in ids

        # Get existing schedule
        get_res = await client.get(f"/v1/refunds/export/schedules/{s1['schedule_id']}")
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Schedule 1"

        # Get nonexistent schedule
        not_found_res = await client.get("/v1/refunds/export/schedules/sch_nonexistent")
        assert not_found_res.status_code == 404
        problem = not_found_res.json()
        assert problem["type"] == "urn:problem:not-found"


@pytest.mark.asyncio
async def test_update_export_schedule():
    """Verify PUT updates fields and handles 404 and invalid columns."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/v1/refunds/export/schedules",
            json={"name": "Old Name", "recipients": ["orig@example.com"]},
        )
        sch_id = create_res.json()["schedule_id"]

        # Valid update
        update_res = await client.put(
            f"/v1/refunds/export/schedules/{sch_id}",
            json={
                "name": "Updated Name",
                "frequency": "weekly",
                "format": "json",
                "enabled": False,
                "columns": ["Refund ID", "Status"],
            },
        )
        assert update_res.status_code == 200
        data = update_res.json()
        assert data["name"] == "Updated Name"
        assert data["frequency"] == "weekly"
        assert data["format"] == "json"
        assert data["enabled"] is False
        assert data["columns"] == ["refund_id", "status"]

        # Update with invalid column
        bad_col_res = await client.put(
            f"/v1/refunds/export/schedules/{sch_id}",
            json={"columns": ["bogus_column"]},
        )
        assert bad_col_res.status_code == 400
        assert bad_col_res.json()["type"] == "urn:problem:bad-request"

        # Update nonexistent
        missing_res = await client.put(
            "/v1/refunds/export/schedules/sch_missing",
            json={"name": "Does not matter"},
        )
        assert missing_res.status_code == 404
        assert missing_res.json()["type"] == "urn:problem:not-found"


@pytest.mark.asyncio
async def test_delete_export_schedule():
    """Verify DELETE removes schedule with 204, subsequent get returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/v1/refunds/export/schedules",
            json={"name": "To Delete", "recipients": ["del@example.com"]},
        )
        sch_id = create_res.json()["schedule_id"]

        del_res = await client.delete(f"/v1/refunds/export/schedules/{sch_id}")
        assert del_res.status_code == 204

        # Verify not found now
        get_res = await client.get(f"/v1/refunds/export/schedules/{sch_id}")
        assert get_res.status_code == 404

        # Delete nonexistent schedule
        del_again = await client.delete(f"/v1/refunds/export/schedules/{sch_id}")
        assert del_again.status_code == 404


@pytest.mark.asyncio
async def test_trigger_export_schedule_csv_manual(mock_repo: MockRefundRepository):
    """Verify triggering CSV export generates email, attachment, logs delivery, and updates schedule status."""
    mock_repo.seed_record("ref_1", "ORD-1", "completed", order_amount=50.0)
    mock_repo.seed_record("ref_2", "ORD-2", "pending", order_amount=75.0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create CSV schedule with filter=completed
        create_res = await client.post(
            "/v1/refunds/export/schedules",
            json={
                "name": "Audit Completed",
                "recipients": ["audit@example.com"],
                "frequency": "daily",
                "format": "csv",
                "status_filter": "completed",
                "columns": ["refund_id", "order_id", "status"],
            },
        )
        sch_id = create_res.json()["schedule_id"]

        # Trigger run
        trigger_res = await client.post(f"/v1/refunds/export/schedules/{sch_id}/trigger")
        assert trigger_res.status_code == 200
        res_data = trigger_res.json()
        assert res_data["schedule_id"] == sch_id
        assert res_data["records_exported"] == 1
        assert res_data["recipients_delivered"] == ["audit@example.com"]
        assert res_data["status"] == "success"
        assert res_data["executed_at"] is not None

        # Verify schedule record was updated
        store = get_export_schedules_store()
        assert store[sch_id]["last_status"] == "success"
        assert store[sch_id]["last_run"] is not None

        # Verify delivered emails log
        delivered = get_delivered_emails()
        assert len(delivered) == 1
        email_record = delivered[0]
        assert email_record["sender"] == "noreply@refunds.example.com"
        assert email_record["recipients"] == ["audit@example.com"]
        assert "Audit Completed" in email_record["subject"]
        assert email_record["attachment_filename"].endswith(".csv")
        assert email_record["attachment_mime_type"] == "text/csv"
        assert email_record["attachment_bytes_len"] > 0

        # Verify MIME parsing of raw message
        parsed_msg = message_from_bytes(email_record["raw_message"])
        assert parsed_msg["From"] == "noreply@refunds.example.com"
        assert parsed_msg["To"] == "audit@example.com"
        assert parsed_msg.is_multipart()


@pytest.mark.asyncio
async def test_trigger_export_schedule_json_manual(mock_repo: MockRefundRepository):
    """Verify triggering JSON export creates valid JSON attachment and delivers."""
    mock_repo.seed_record("ref_10", "ORD-10", "completed", order_amount=120.0)
    mock_repo.seed_record("ref_11", "ORD-11", "completed", order_amount=40.0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/v1/refunds/export/schedules",
            json={
                "name": "Finance Export",
                "recipients": ["finance@example.com"],
                "frequency": "weekly",
                "format": "json",
            },
        )
        sch_id = create_res.json()["schedule_id"]

        trigger_res = await client.post(f"/v1/refunds/export/schedules/{sch_id}/trigger")
        assert trigger_res.status_code == 200
        res_data = trigger_res.json()
        assert res_data["records_exported"] == 2
        assert res_data["status"] == "success"

        delivered = get_delivered_emails()
        assert len(delivered) == 1
        record = delivered[0]
        assert record["attachment_mime_type"] == "application/json"
        assert record["attachment_filename"].endswith(".json")


@pytest.mark.asyncio
async def test_trigger_export_schedule_not_found():
    """Verify triggering nonexistent schedule returns 404 ProblemDetails."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/v1/refunds/export/schedules/sch_nonexistent/trigger")
        assert res.status_code == 404
        assert res.json()["type"] == "urn:problem:not-found"


def test_send_export_report_email_with_mock_ses():
    """Direct test of send_export_report_email with mock SES client."""
    mock_ses = MagicMock()
    mock_ses.send_raw_email.return_value = {"MessageId": "ses-msg-12345"}

    clear_delivered_emails()
    delivery = send_export_report_email(
        sender="test@example.com",
        recipients=["user@example.com"],
        subject="Test Report",
        body_text="Plain text body",
        body_html="<p>HTML body</p>",
        attachment_filename="export.csv",
        attachment_bytes=b"col1,col2\nval1,val2\n",
        attachment_mime_type="text/csv",
        ses_client=mock_ses,
    )

    mock_ses.send_raw_email.assert_called_once()
    assert delivery["message_id"] == "ses-msg-12345"
    assert delivery["status"] == "success"

    # Verify recorded in _delivered_emails
    assert len(get_delivered_emails()) == 1
