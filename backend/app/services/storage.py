"""Evidence storage service supporting Amazon S3 and local filesystem fallback."""

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
import uuid

import boto3
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# Allowed media types
ALLOWED_IMAGE_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

ALLOWED_CONTENT_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

# Size limits (5MB for images)
MAX_IMAGE_SIZE_BYTES: int = 5 * 1024 * 1024


def sanitize_filename(filename: str) -> str:
    """Sanitize user-provided filename preventing path traversal and unsafe characters.

    Strips directory separators, eliminates traversal sequences ('../', '..\\'),
    replaces special characters with underscores, and strips leading dots.
    """
    # Normalize slashes and extract pure basename
    normalized = filename.replace("\\", "/").rstrip("/")
    basename = normalized.split("/")[-1] if "/" in normalized else normalized

    # Strip any remaining directory traversal dots
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", basename)
    cleaned = cleaned.lstrip(".")

    return cleaned if cleaned else "evidence_file"


def validate_file(file_bytes: bytes, content_type: str) -> None:
    """Validate media type and enforce maximum file size limits.

    Raises:
        ValueError: If content_type is not authorized or file exceeds size limits.
    """
    normalized_type = content_type.lower().strip()
    if normalized_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"Unsupported content type: '{content_type}'. "
            f"Allowed types are: {sorted(ALLOWED_CONTENT_TYPES)}"
        )

    size = len(file_bytes)
    if size > MAX_IMAGE_SIZE_BYTES:
        raise ValueError(
            f"File size ({size} bytes) exceeds maximum allowed limit of "
            f"{MAX_IMAGE_SIZE_BYTES} bytes (5MB) for images."
        )


def generate_storage_key(refund_id: str, filename: str, order_id: str | None = None) -> str:
    """Generate a sanitized, hierarchical storage key.

    Format: evidence/{order_id or refund_id}/{uuid}_{sanitized_filename}
    """
    sanitized_name = sanitize_filename(filename)
    folder_raw = order_id.strip() if order_id and order_id.strip() else refund_id.strip()
    folder_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", folder_raw)
    file_uid = uuid.uuid4().hex[:8]

    return f"evidence/{folder_clean}/{file_uid}_{sanitized_name}"


class EvidenceStorageService:
    """Evidence storage service managing uploads, retrieval, and URLs with S3 and local fallback."""

    def __init__(
        self,
        s3_client: Any = None,
        bucket_name: str | None = None,
        local_dir: str | Path | None = None,
        settings: Settings | None = None,
        storage_backend: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bucket_name = bucket_name or self.settings.s3_bucket_evidence
        self.s3_endpoint_url = self.settings.s3_endpoint_url

        if local_dir is not None:
            self.local_dir = Path(local_dir).resolve()
        else:
            cfg_dir = Path(self.settings.local_storage_dir)
            self.local_dir = cfg_dir.resolve() if cfg_dir.is_absolute() else (_BACKEND_DIR / cfg_dir).resolve()

        if storage_backend is not None:
            self.storage_backend = storage_backend
            self.s3_client = s3_client
        elif s3_client is not None:
            self.storage_backend = "s3"
            self.s3_client = s3_client
        elif self.s3_endpoint_url:
            kwargs: dict[str, Any] = {
                "region_name": self.settings.aws_region,
                "endpoint_url": self.s3_endpoint_url,
            }
            if self.settings.aws_access_key_id and self.settings.aws_secret_access_key:
                kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
                if self.settings.aws_session_token:
                    kwargs["aws_session_token"] = self.settings.aws_session_token
            self.s3_client = boto3.client("s3", **kwargs)
            self.storage_backend = "s3"
        else:
            self.s3_client = None
            self.storage_backend = "local"

    def generate_storage_key(
        self, refund_id: str, filename: str, order_id: str | None = None
    ) -> str:
        """Generate a secure, hierarchical storage key."""
        return generate_storage_key(refund_id=refund_id, filename=filename, order_id=order_id)

    def validate_file(self, file_bytes: bytes, content_type: str) -> None:
        """Validate media type and size constraints."""
        validate_file(file_bytes=file_bytes, content_type=content_type)

    def get_file_url(self, storage_key: str) -> str:
        """Return an accessible URL for a given storage key."""
        if self.storage_backend == "s3":
            if self.s3_endpoint_url:
                base_url = self.s3_endpoint_url.rstrip("/")
                return f"{base_url}/{self.bucket_name}/{storage_key}"
            return f"https://{self.bucket_name}.s3.amazonaws.com/{storage_key}"
        return f"/static/uploads/{storage_key}"

    def save_file(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        refund_id: str,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate, store, and return metadata for an evidence file."""
        self.validate_file(file_bytes=file_bytes, content_type=content_type)
        storage_key = self.generate_storage_key(
            refund_id=refund_id, filename=filename, order_id=order_id
        )
        sanitized_base_filename = sanitize_filename(filename)

        if self.storage_backend == "s3":
            if self.s3_client is None:
                raise RuntimeError("S3 client is not configured for evidence storage.")
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=storage_key,
                Body=file_bytes,
                ContentType=content_type,
            )
            url = self.get_file_url(storage_key)
        else:
            target_path = (self.local_dir / storage_key).resolve()
            if not str(target_path).startswith(str(self.local_dir)):
                raise ValueError("Path traversal attempt detected in target path.")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(file_bytes)
            url = self.get_file_url(storage_key)

        created_at = datetime.now(timezone.utc).isoformat()
        return {
            "storage_key": storage_key,
            "filename": sanitized_base_filename,
            "content_type": content_type,
            "size_bytes": len(file_bytes),
            "url": url,
            "storage_backend": self.storage_backend,
            "created_at": created_at,
        }

    def get_file(self, storage_key: str) -> bytes:
        """Retrieve raw file bytes from S3 or local filesystem.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        if self.storage_backend == "s3":
            if self.s3_client is None:
                raise RuntimeError("S3 client is not configured for evidence storage.")
            try:
                response = self.s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=storage_key,
                )
                body = response.get("Body")
                if hasattr(body, "read"):
                    return body.read()
                return bytes(body)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ("NoSuchKey", "404", "NotFound"):
                    raise FileNotFoundError(f"Evidence file not found in S3: {storage_key}") from e
                raise
            except Exception as e:
                if "NoSuchKey" in str(e) or "NotFound" in str(e):
                    raise FileNotFoundError(f"Evidence file not found in S3: {storage_key}") from e
                raise
        else:
            target_path = (self.local_dir / storage_key).resolve()
            if not str(target_path).startswith(str(self.local_dir)):
                raise ValueError("Path traversal attempt detected in target path.")
            if not target_path.is_file():
                raise FileNotFoundError(f"Evidence file not found locally: {storage_key}")
            return target_path.read_bytes()


def get_evidence_storage_service() -> EvidenceStorageService:
    """Dependency provider returning an EvidenceStorageService instance."""
    return EvidenceStorageService()
