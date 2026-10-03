"""Unit tests for EvidenceStorageService with local filesystem and Amazon S3 backends."""

from datetime import datetime
import io
from pathlib import Path
import struct
from unittest.mock import MagicMock
import pytest
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.services.storage import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE_BYTES,
    EvidenceStorageService,
    generate_storage_key,
    get_evidence_storage_service,
    sanitize_filename,
    validate_file,
)

VALID_SAMPLE_IMAGES: dict[str, bytes] = {
    "image/jpeg": (
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + struct.pack(">HH", 50, 50)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    ),
    "image/png": (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + struct.pack(">II", 50, 50)
        + b"\x08\x02\x00\x00\x00\x00\x00\x00\x00"
    ),
    "image/webp": (
        b"RIFF\x1a\x00\x00\x00WEBPVP8L\x05\x00\x00\x00\x2f"
        + struct.pack("<I", (49 & 0x3FFF) | ((49 & 0x3FFF) << 14))
    ),
}


# --- Filename Sanitization & Storage Key Tests ---


def test_sanitize_filename_strips_path_traversal():
    """Verify path traversal sequences and separators are stripped."""
    assert sanitize_filename("../../etc/passwd.jpg") == "passwd.jpg"
    assert sanitize_filename("..\\..\\windows\\system32\\calc.png") == "calc.png"
    assert sanitize_filename("../../../damage.webp") == "damage.webp"
    assert sanitize_filename("safe_photo.jpeg") == "safe_photo.jpeg"


def test_sanitize_filename_replaces_unsafe_characters():
    """Verify special characters are replaced with underscores."""
    raw = "damaged box & broken screen (1) #final.jpg"
    sanitized = sanitize_filename(raw)
    assert "&" not in sanitized
    assert "(" not in sanitized
    assert "#" not in sanitized
    assert sanitized.endswith(".jpg")


def test_sanitize_filename_empty_or_dots_fallback():
    """Verify empty or pure dot filenames fall back to evidence_file."""
    assert sanitize_filename("") == "evidence_file"
    assert sanitize_filename("...") == "evidence_file"
    assert sanitize_filename("///") == "evidence_file"


def test_generate_storage_key_with_order_id():
    """Verify storage key uses order_id when provided."""
    key = generate_storage_key(refund_id="REF-12345", filename="broken_lens.png", order_id="ORD-1001")
    assert key.startswith("evidence/ORD-1001/")
    assert key.endswith("_broken_lens.png")


def test_generate_storage_key_with_refund_id_fallback():
    """Verify storage key falls back to refund_id when order_id is None."""
    key = generate_storage_key(refund_id="REF-12345", filename="broken_lens.png", order_id=None)
    assert key.startswith("evidence/REF-12345/")
    assert key.endswith("_broken_lens.png")


# --- Media Type & Size Limits Validation Tests ---


@pytest.mark.parametrize("content_type", sorted(ALLOWED_IMAGE_TYPES))
def test_validate_file_allowed_images(content_type: str):
    """Verify all allowed image MIME types (JPEG, PNG, WebP) pass validation within 5MB."""
    sample_bytes = VALID_SAMPLE_IMAGES[content_type]
    # Should not raise
    validate_file(sample_bytes, content_type)


@pytest.mark.parametrize("video_type", ["video/mp4", "video/quicktime"])
def test_validate_file_rejects_video_mime_types(video_type: str):
    """Verify video MIME types are rejected with ValueError stating allowed types."""
    sample_bytes = b"\x00" * 1024
    with pytest.raises(ValueError, match="Unsupported content type") as exc_info:
        validate_file(sample_bytes, video_type)
    assert "Allowed types are: ['image/jpeg', 'image/png', 'image/webp']" in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_type",
    [
        "application/pdf",
        "text/html",
        "text/plain",
        "application/json",
        "application/x-sh",
        "image/gif",
        "image/bmp",
    ],
)
def test_validate_file_disallowed_mime_types(invalid_type: str):
    """Verify disallowed MIME types raise ValueError."""
    sample_bytes = b"\x00" * 100
    with pytest.raises(ValueError, match="Unsupported content type"):
        validate_file(sample_bytes, invalid_type)


def test_validate_file_image_size_exceeded():
    """Verify file exceeding 5MB ceiling raises ValueError."""
    oversized_bytes = b"x" * (MAX_IMAGE_SIZE_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds maximum allowed limit of 5242880 bytes"):
        validate_file(oversized_bytes, "image/jpeg")


# --- Local Storage Backend Tests ---


def test_local_storage_save_retrieval_and_metadata(tmp_path: Path):
    """Verify local filesystem save, retrieval, metadata calculation, and directory auto-creation."""
    service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    payload = VALID_SAMPLE_IMAGES["image/jpeg"]

    metadata = service.save_file(
        file_bytes=payload,
        filename="../../evidence/damage.jpeg",
        content_type="image/jpeg",
        refund_id="REF-1001",
        order_id="ORD-1001",
    )

    # Verify metadata fields
    assert metadata["storage_backend"] == "local"
    assert metadata["filename"] == "damage.jpeg"
    assert metadata["content_type"] == "image/jpeg"
    assert metadata["size_bytes"] == len(payload)
    assert metadata["width"] == 50
    assert metadata["height"] == 50
    assert metadata["format"] == "jpeg"
    assert metadata["storage_key"].startswith("evidence/ORD-1001/")
    assert metadata["url"] == f"/static/uploads/{metadata['storage_key']}"
    # Verify ISO timestamp
    datetime.fromisoformat(metadata["created_at"])

    # Verify physical file existence in tmp_path
    disk_path = tmp_path / metadata["storage_key"]
    assert disk_path.is_file()
    assert disk_path.read_bytes() == payload

    # Verify retrieval via get_file
    retrieved = service.get_file(metadata["storage_key"])
    assert retrieved == payload


def test_local_storage_get_file_not_found(tmp_path: Path):
    """Verify get_file raises FileNotFoundError if file does not exist locally."""
    service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    with pytest.raises(FileNotFoundError, match="Evidence file not found locally"):
        service.get_file("evidence/ORD-1001/missing.png")


def test_local_storage_get_file_url():
    """Verify get_file_url produces correct local static path."""
    service = EvidenceStorageService(storage_backend="local")
    url = service.get_file_url("evidence/ORD-1001/uuid_photo.png")
    assert url == "/static/uploads/evidence/ORD-1001/uuid_photo.png"


# --- S3 Storage Backend Tests ---


def test_s3_storage_save_retrieval_and_metadata():
    """Verify S3 save and retrieval using a mocked boto3 S3 client."""
    mock_s3 = MagicMock()
    mock_body = MagicMock()
    mock_body.read.return_value = b"s3-stored-image-bytes"
    mock_s3.get_object.return_value = {"Body": mock_body}

    service = EvidenceStorageService(
        s3_client=mock_s3,
        bucket_name="my-evidence-bucket",
    )

    payload = VALID_SAMPLE_IMAGES["image/png"]
    mock_body.read.return_value = payload
    metadata = service.save_file(
        file_bytes=payload,
        filename="broken_screen.png",
        content_type="image/png",
        refund_id="REF-2002",
        order_id="ORD-2002",
    )

    # Verify S3 put_object invocation
    mock_s3.put_object.assert_called_once_with(
        Bucket="my-evidence-bucket",
        Key=metadata["storage_key"],
        Body=payload,
        ContentType="image/png",
    )

    # Verify metadata fields
    assert metadata["storage_backend"] == "s3"
    assert metadata["filename"] == "broken_screen.png"
    assert metadata["content_type"] == "image/png"
    assert metadata["size_bytes"] == len(payload)
    assert metadata["width"] == 50
    assert metadata["height"] == 50
    assert metadata["format"] == "png"
    assert metadata["url"] == f"https://my-evidence-bucket.s3.amazonaws.com/{metadata['storage_key']}"

    # Verify S3 get_object retrieval
    retrieved = service.get_file(metadata["storage_key"])
    assert retrieved == payload
    mock_s3.get_object.assert_called_once_with(
        Bucket="my-evidence-bucket",
        Key=metadata["storage_key"],
    )


def test_s3_storage_get_file_not_found():
    """Verify get_file raises FileNotFoundError when S3 returns NoSuchKey ClientError."""
    mock_s3 = MagicMock()
    error_response = {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}}
    mock_s3.get_object.side_effect = ClientError(error_response, "GetObject")

    service = EvidenceStorageService(s3_client=mock_s3, bucket_name="evidence-bucket")

    with pytest.raises(FileNotFoundError, match="Evidence file not found in S3"):
        service.get_file("evidence/ORD-1001/missing.jpg")


def test_s3_storage_with_custom_endpoint_url():
    """Verify S3 URL generation when s3_endpoint_url is configured (e.g. LocalStack)."""
    settings = Settings(
        s3_bucket_evidence="custom-bucket",
        s3_endpoint_url="http://localhost:4566",
        _env_file=None,
    )
    mock_s3 = MagicMock()
    service = EvidenceStorageService(s3_client=mock_s3, settings=settings)

    url = service.get_file_url("evidence/ORD-9999/test.webp")
    assert url == "http://localhost:4566/custom-bucket/evidence/ORD-9999/test.webp"


# --- Service Initialization & Dependency Provider Tests ---


def test_service_initialization_defaults():
    """Verify default initialization sets local storage backend and default bucket."""
    service = EvidenceStorageService()
    assert service.storage_backend == "local"
    assert service.bucket_name == "refund-request-evidence"
    assert service.s3_client is None
    assert service.local_dir.is_absolute()


def test_get_evidence_storage_service_factory():
    """Verify dependency provider returns an initialized EvidenceStorageService."""
    service = get_evidence_storage_service()
    assert isinstance(service, EvidenceStorageService)
    assert service.storage_backend == "local"
