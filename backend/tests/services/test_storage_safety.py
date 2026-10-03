"""Unit tests for automated image format, magic byte safety validation, and dimension parsing.

Tests verify:
- Binary magic byte validation for JPEG, PNG, and WebP (VP8, VP8L, VP8X).
- Pure-Python struct dimension parsing without third-party libraries.
- Detection and rejection of spoofed files and MIME-type contradictions.
- Rejection of truncated, empty, or corrupt headers with ValueError.
- Resolution bounds enforcement (minimum 50x50, maximum 8192x8192).
- Acceptance of exact boundary resolutions (50x50 and 8192x8192).
- Metadata enrichment with width, height, and detected format in save_file.
"""

from pathlib import Path
import struct
import pytest

from app.services.storage import (
    EvidenceStorageService,
    _parse_jpeg_dimensions,
    _parse_png_dimensions,
    _parse_webp_dimensions,
    validate_file,
)


# --- Image Byte Generation Helpers for Pure-Python Dimension Testing ---


def make_png(width: int, height: int) -> bytes:
    """Generate a minimal valid PNG binary payload with specified dimensions in IHDR."""
    header = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: 4 bytes len (13), 4 bytes type ('IHDR'), 4 bytes w, 4 bytes h, 5 bytes specs, 4 bytes crc
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr_chunk = b"\x00\x00\x00\x0dIHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return header + ihdr_chunk


def make_jpeg(width: int, height: int, marker: int = 0xC0) -> bytes:
    """Generate a minimal valid JPEG binary payload with specified dimensions in SOF marker."""
    # SOI
    soi = b"\xff\xd8"
    # SOF marker: 0xFF followed by marker byte (e.g. 0xC0 for SOF0)
    # Payload length (17 bytes), precision (8), height (2 bytes), width (2 bytes), 3 components (9 bytes)
    payload_len = 17
    sof_payload = (
        struct.pack(">H", payload_len)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    sof = b"\xff" + bytes([marker]) + sof_payload
    # EOI
    eoi = b"\xff\xd9"
    return soi + sof + eoi


def make_webp_lossless(width: int, height: int) -> bytes:
    """Generate a minimal valid WebP VP8L lossless binary payload."""
    packed = ((width - 1) & 0x3FFF) | (((height - 1) & 0x3FFF) << 14)
    vp8l_data = b"\x2f" + struct.pack("<I", packed)
    chunk = b"VP8L" + struct.pack("<I", len(vp8l_data)) + vp8l_data
    riff_header = b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP"
    return riff_header + chunk


def make_webp_lossy(width: int, height: int) -> bytes:
    """Generate a minimal valid WebP VP8 lossy binary payload."""
    # VP8 frame tag (3 bytes), start code (3 bytes: 0x9D, 0x01, 0x2A), 2 bytes w, 2 bytes h
    vp8_data = (
        b"\x00\x00\x00\x9d\x01\x2a"
        + struct.pack("<H", width & 0x3FFF)
        + struct.pack("<H", height & 0x3FFF)
    )
    chunk = b"VP8 " + struct.pack("<I", len(vp8_data)) + vp8_data
    riff_header = b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP"
    return riff_header + chunk


def make_webp_extended(width: int, height: int) -> bytes:
    """Generate a minimal valid WebP VP8X extended binary payload."""
    w_bytes = struct.pack("<I", width - 1)[:3]
    h_bytes = struct.pack("<I", height - 1)[:3]
    vp8x_data = b"\x00\x00\x00\x00" + w_bytes + h_bytes
    chunk = b"VP8X" + struct.pack("<I", len(vp8x_data)) + vp8x_data
    riff_header = b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP"
    return riff_header + chunk


# --- Magic Byte Inspection & Dimension Extraction Tests ---


def test_png_magic_byte_and_dimension_parsing():
    """Verify PNG binary signature and IHDR dimension extraction via struct."""
    png_bytes = make_png(640, 480)
    width, height = _parse_png_dimensions(png_bytes)
    assert width == 640
    assert height == 480

    w, h, fmt = validate_file(png_bytes, "image/png")
    assert (w, h, fmt) == (640, 480, "png")


@pytest.mark.parametrize("marker", [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB])
def test_jpeg_magic_byte_and_sof_dimension_parsing(marker: int):
    """Verify JPEG binary signature and SOF dimension extraction across multiple SOF markers."""
    jpeg_bytes = make_jpeg(800, 600, marker=marker)
    width, height = _parse_jpeg_dimensions(jpeg_bytes)
    assert width == 800
    assert height == 600

    w, h, fmt = validate_file(jpeg_bytes, "image/jpeg")
    assert (w, h, fmt) == (800, 600, "jpeg")


def test_webp_lossless_vp8l_dimension_parsing():
    """Verify WebP VP8L lossless dimension parsing via struct bit unpacking."""
    webp_bytes = make_webp_lossless(1024, 768)
    width, height = _parse_webp_dimensions(webp_bytes)
    assert width == 1024
    assert height == 768

    w, h, fmt = validate_file(webp_bytes, "image/webp")
    assert (w, h, fmt) == (1024, 768, "webp")


def test_webp_lossy_vp8_dimension_parsing():
    """Verify WebP VP8 lossy dimension parsing via struct unpack."""
    webp_bytes = make_webp_lossy(1280, 720)
    width, height = _parse_webp_dimensions(webp_bytes)
    assert width == 1280
    assert height == 720

    w, h, fmt = validate_file(webp_bytes, "image/webp")
    assert (w, h, fmt) == (1280, 720, "webp")


def test_webp_extended_vp8x_dimension_parsing():
    """Verify WebP VP8X extended canvas dimension parsing via struct unpack."""
    webp_bytes = make_webp_extended(1920, 1080)
    width, height = _parse_webp_dimensions(webp_bytes)
    assert width == 1920
    assert height == 1080

    w, h, fmt = validate_file(webp_bytes, "image/webp")
    assert (w, h, fmt) == (1920, 1080, "webp")


# --- Spoofed Files & Signature Mismatches ---


@pytest.mark.parametrize(
    "spoofed_content, declared_mime",
    [
        (b"<!DOCTYPE html><html><body>Login</body></html>", "image/jpeg"),
        (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff", "image/png"),
        (b"This is a plain text file pretending to be an image.", "image/webp"),
        (b"%PDF-1.4\n%...\n1 0 obj\n<<>>\nendobj", "image/jpeg"),
        (b"{\"type\": \"json_payload\", \"key\": \"value\"}", "image/png"),
    ],
)
def test_validate_file_rejects_spoofed_files(spoofed_content: bytes, declared_mime: str):
    """Verify non-image content disguised under image MIME types is rejected."""
    with pytest.raises(
        ValueError, match="File signature does not match allowed image formats"
    ):
        validate_file(spoofed_content, declared_mime)


def test_validate_file_rejects_mime_type_contradiction():
    """Verify valid PNG content uploaded with declared image/jpeg MIME type is rejected."""
    png_bytes = make_png(100, 100)
    with pytest.raises(ValueError, match="File signature does not match declared MIME type"):
        validate_file(png_bytes, "image/jpeg")

    jpeg_bytes = make_jpeg(100, 100)
    with pytest.raises(ValueError, match="File signature does not match declared MIME type"):
        validate_file(jpeg_bytes, "image/png")


# --- Truncated, Corrupt, or Empty Headers ---


@pytest.mark.parametrize(
    "corrupt_bytes, mime",
    [
        (b"", "image/jpeg"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"\xff\xd8\xff\xc0\x00", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dXXXX", "image/png"),
        (b"RIFF\x04\x00\x00\x00WEBP", "image/webp"),
        (b"RIFF\x10\x00\x00\x00WEBPVP8L\x02\x00\x00\x00\x00\x00", "image/webp"),
    ],
)
def test_validate_file_rejects_corrupted_or_truncated_headers(corrupt_bytes: bytes, mime: str):
    """Verify truncated or corrupt image headers raise ValueError with descriptive message."""
    with pytest.raises(ValueError, match="Invalid or corrupt image header"):
        validate_file(corrupt_bytes, mime)


# --- Resolution Bounds Tests ---


@pytest.mark.parametrize(
    "width, height",
    [
        (49, 50),
        (50, 49),
        (10, 10),
        (1, 100),
    ],
)
def test_validate_file_rejects_under_resolution(width: int, height: int):
    """Verify images below 50x50 resolution threshold raise ValueError with dimensions."""
    png_bytes = make_png(width, height)
    expected_msg = f"Image dimensions ({width}x{height}) are below minimum required resolution of 50x50 pixels."
    with pytest.raises(ValueError, match=expected_msg.replace("(", r"\(").replace(")", r"\)")):
        validate_file(png_bytes, "image/png")


@pytest.mark.parametrize(
    "width, height",
    [
        (8193, 100),
        (100, 8193),
        (10000, 10000),
    ],
)
def test_validate_file_rejects_over_resolution(width: int, height: int):
    """Verify images exceeding 8192x8192 resolution threshold raise ValueError with dimensions."""
    png_bytes = make_png(width, height)
    expected_msg = f"Image dimensions ({width}x{height}) exceed maximum allowed resolution of 8192x8192 pixels."
    with pytest.raises(ValueError, match=expected_msg.replace("(", r"\(").replace(")", r"\)")):
        validate_file(png_bytes, "image/png")


@pytest.mark.parametrize(
    "width, height",
    [
        (50, 50),
        (8192, 8192),
        (50, 8192),
        (8192, 50),
    ],
)
def test_validate_file_accepts_exact_boundary_resolutions(width: int, height: int):
    """Verify exact resolution boundaries (50x50, 8192x8192) are cleanly accepted."""
    png_bytes = make_png(width, height)
    w, h, fmt = validate_file(png_bytes, "image/png")
    assert w == width
    assert h == height
    assert fmt == "png"


# --- EvidenceStorageService save_file Metadata Enrichment Tests ---


def test_storage_service_save_file_enriches_metadata(tmp_path: Path):
    """Verify save_file enriches returned metadata with width, height, and format."""
    service = EvidenceStorageService(local_dir=tmp_path, storage_backend="local")
    png_bytes = make_png(120, 180)

    metadata = service.save_file(
        file_bytes=png_bytes,
        filename="proof.png",
        content_type="image/png",
        refund_id="ref_test_01",
        order_id="ORD-7777",
    )

    assert metadata["width"] == 120
    assert metadata["height"] == 180
    assert metadata["format"] == "png"
    assert metadata["size_bytes"] == len(png_bytes)
    assert metadata["filename"] == "proof.png"
    assert metadata["storage_key"].startswith("evidence/ORD-7777/")
