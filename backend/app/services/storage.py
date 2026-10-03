"""Evidence storage service supporting Amazon S3 and local filesystem fallback."""

from datetime import datetime, timezone
from pathlib import Path
import re
import struct
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

# Resolution limits
MIN_IMAGE_DIMENSION: int = 50
MAX_IMAGE_DIMENSION: int = 8192

MIME_TO_FORMAT: dict[str, str] = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
}


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


def _parse_png_dimensions(file_bytes: bytes) -> tuple[int, int]:
    """Extract width and height from PNG IHDR chunk using struct."""
    if len(file_bytes) < 24:
        raise ValueError("Invalid or corrupt image header")
    if file_bytes[12:16] != b"IHDR":
        raise ValueError("Invalid or corrupt image header")
    width, height = struct.unpack(">II", file_bytes[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("Invalid or corrupt image header")
    return width, height


def _parse_jpeg_dimensions(file_bytes: bytes) -> tuple[int, int]:
    """Extract width and height from JPEG Start of Frame (SOF) markers using struct."""
    length = len(file_bytes)
    offset = 2
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}

    while offset < length:
        if file_bytes[offset] != 0xFF:
            offset += 1
            continue
        while offset < length and file_bytes[offset] == 0xFF:
            offset += 1
        if offset >= length:
            break
        marker = file_bytes[offset]
        offset += 1

        if marker in (0xD9, 0xDA):
            break

        if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7):
            continue

        if offset + 2 > length:
            raise ValueError("Invalid or corrupt image header")

        payload_len = struct.unpack(">H", file_bytes[offset : offset + 2])[0]
        if payload_len < 2:
            raise ValueError("Invalid or corrupt image header")

        if marker in sof_markers:
            if offset + 7 > length:
                raise ValueError("Invalid or corrupt image header")
            height, width = struct.unpack(">HH", file_bytes[offset + 3 : offset + 7])
            if width <= 0 or height <= 0:
                raise ValueError("Invalid or corrupt image header")
            return width, height

        offset += payload_len

    raise ValueError("Invalid or corrupt image header")


def _parse_webp_dimensions(file_bytes: bytes) -> tuple[int, int]:
    """Extract width and height from WebP VP8, VP8L, or VP8X chunks using struct."""
    length = len(file_bytes)
    if length < 12:
        raise ValueError("Invalid or corrupt image header")
    if file_bytes[:4] != b"RIFF" or file_bytes[8:12] != b"WEBP":
        raise ValueError("Invalid or corrupt image header")

    offset = 12
    while offset + 8 <= length:
        chunk_fourcc = file_bytes[offset : offset + 4]
        chunk_size = struct.unpack("<I", file_bytes[offset + 4 : offset + 8])[0]
        chunk_data_offset = offset + 8
        chunk_end = chunk_data_offset + chunk_size

        if chunk_fourcc == b"VP8 ":
            if chunk_data_offset + 10 > length:
                raise ValueError("Invalid or corrupt image header")
            if file_bytes[chunk_data_offset + 3 : chunk_data_offset + 6] != b"\x9d\x01\x2a":
                raise ValueError("Invalid or corrupt image header")
            width = struct.unpack("<H", file_bytes[chunk_data_offset + 6 : chunk_data_offset + 8])[0] & 0x3FFF
            height = struct.unpack("<H", file_bytes[chunk_data_offset + 8 : chunk_data_offset + 10])[0] & 0x3FFF
            if width <= 0 or height <= 0:
                raise ValueError("Invalid or corrupt image header")
            return width, height

        elif chunk_fourcc == b"VP8L":
            if chunk_data_offset + 5 > length:
                raise ValueError("Invalid or corrupt image header")
            if file_bytes[chunk_data_offset] != 0x2F:
                raise ValueError("Invalid or corrupt image header")
            bits = struct.unpack("<I", file_bytes[chunk_data_offset + 1 : chunk_data_offset + 5])[0]
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height

        elif chunk_fourcc == b"VP8X":
            if chunk_data_offset + 10 > length:
                raise ValueError("Invalid or corrupt image header")
            canvas_w_bytes = file_bytes[chunk_data_offset + 4 : chunk_data_offset + 7] + b"\x00"
            canvas_h_bytes = file_bytes[chunk_data_offset + 7 : chunk_data_offset + 10] + b"\x00"
            width = struct.unpack("<I", canvas_w_bytes)[0] + 1
            height = struct.unpack("<I", canvas_h_bytes)[0] + 1
            return width, height

        offset = chunk_end + (chunk_size % 2)

    raise ValueError("Invalid or corrupt image header")


def validate_file(file_bytes: bytes, content_type: str) -> tuple[int, int, str]:
    """Validate media type, binary magic bytes, resolution bounds, and size limits.

    Returns:
        tuple[int, int, str]: (width, height, detected_format) where detected_format
        is 'jpeg', 'png', or 'webp'.

    Raises:
        ValueError: If content_type is unsupported, file exceeds 5MB, binary signature
        fails verification or contradicts declared MIME type, headers are corrupt/truncated,
        or image dimensions fall outside 50x50 to 8192x8192 pixels.
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

    if size == 0:
        raise ValueError("Invalid or corrupt image header")

    # Magic byte inspection
    detected_format: str
    if file_bytes.startswith(b"\xff\xd8\xff"):
        detected_format = "jpeg"
    elif file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_format = "png"
    elif file_bytes.startswith(b"RIFF") and len(file_bytes) >= 12 and file_bytes[8:12] == b"WEBP":
        detected_format = "webp"
    else:
        # Differentiate between truncated known magic prefix and non-image spoofed content
        if file_bytes.startswith(b"\xff\xd8") or file_bytes.startswith(b"\x89PNG") or file_bytes.startswith(b"RIFF"):
            raise ValueError("Invalid or corrupt image header")
        raise ValueError("File signature does not match allowed image formats (JPEG, PNG, WebP)")

    # MIME type contradiction check
    expected_format = MIME_TO_FORMAT.get(normalized_type)
    if expected_format is not None and detected_format != expected_format:
        raise ValueError(
            f"File signature does not match declared MIME type '{content_type}' "
            f"(detected '{detected_format}')."
        )

    # Dimension extraction
    if detected_format == "jpeg":
        width, height = _parse_jpeg_dimensions(file_bytes)
    elif detected_format == "png":
        width, height = _parse_png_dimensions(file_bytes)
    elif detected_format == "webp":
        width, height = _parse_webp_dimensions(file_bytes)
    else:
        raise ValueError("File signature does not match allowed image formats (JPEG, PNG, WebP)")

    # Resolution bounds enforcement
    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        raise ValueError(
            f"Image dimensions ({width}x{height}) are below minimum required resolution of {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION} pixels."
        )
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValueError(
            f"Image dimensions ({width}x{height}) exceed maximum allowed resolution of {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} pixels."
        )

    return width, height, detected_format


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

    def validate_file(self, file_bytes: bytes, content_type: str) -> tuple[int, int, str]:
        """Validate media type, binary magic bytes, dimensions, and size constraints."""
        return validate_file(file_bytes=file_bytes, content_type=content_type)

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
        width, height, detected_format = self.validate_file(
            file_bytes=file_bytes, content_type=content_type
        )
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
            "width": width,
            "height": height,
            "format": detected_format,
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
