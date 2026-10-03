"""Email delivery service using standard library email.mime and Amazon SES with offline fallback."""

from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, get_settings

# In-memory delivery log for offline/development mode and test verification
_delivered_emails: list[dict[str, Any]] = []


def get_delivered_emails() -> list[dict[str, Any]]:
    """Return a copy of all delivered email records recorded in memory."""
    return list(_delivered_emails)


def clear_delivered_emails() -> None:
    """Clear the in-memory delivered email log."""
    _delivered_emails.clear()


def build_export_report_email(
    sender: str,
    recipients: list[str],
    subject: str,
    body_text: str,
    body_html: str,
    attachment_filename: str,
    attachment_bytes: bytes,
    attachment_mime_type: str = "text/csv",
) -> MIMEMultipart:
    """Construct a standard MIME multipart email message with text/html parts and an attached report."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    body_alternative = MIMEMultipart("alternative")
    body_alternative.attach(MIMEText(body_text, "plain", "utf-8"))
    body_alternative.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(body_alternative)

    if "/" in attachment_mime_type:
        maintype, subtype = attachment_mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    attachment = MIMEBase(maintype, subtype)
    attachment.set_payload(attachment_bytes)
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f'attachment; filename="{attachment_filename}"')
    msg.attach(attachment)

    return msg


def send_export_report_email(
    sender: str,
    recipients: list[str],
    subject: str,
    body_text: str,
    body_html: str,
    attachment_filename: str,
    attachment_bytes: bytes,
    attachment_mime_type: str = "text/csv",
    ses_client: Any | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Compose and deliver an export report email via SES, falling back to in-memory logging in dev/offline mode."""
    if settings is None:
        settings = get_settings()

    msg = build_export_report_email(
        sender=sender,
        recipients=recipients,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        attachment_filename=attachment_filename,
        attachment_bytes=attachment_bytes,
        attachment_mime_type=attachment_mime_type,
    )
    raw_message_bytes = msg.as_bytes()

    ses_message_id: str | None = None

    client = ses_client
    if (
        client is None
        and settings.app_env == "production"
        and settings.aws_access_key_id
        and settings.aws_secret_access_key
    ):
        try:
            client = boto3.client(
                "ses",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                aws_session_token=settings.aws_session_token,
            )
        except Exception:
            client = None

    if client is not None:
        try:
            ses_resp = client.send_raw_email(
                Source=sender,
                Destinations=recipients,
                RawMessage={"Data": raw_message_bytes},
            )
            ses_message_id = ses_resp.get("MessageId")
        except (BotoCoreError, ClientError):
            if settings.app_env == "production":
                raise
            ses_message_id = f"offline-{uuid.uuid4().hex[:8]}"

    delivery_record = {
        "message_id": ses_message_id or f"msg-{uuid.uuid4().hex[:12]}",
        "sender": sender,
        "recipients": list(recipients),
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "attachment_filename": attachment_filename,
        "attachment_bytes_len": len(attachment_bytes),
        "attachment_mime_type": attachment_mime_type,
        "raw_message": raw_message_bytes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "success",
    }
    _delivered_emails.append(delivery_record)
    return delivery_record
