"""Unit and integration tests for multimodal image spatial context and resolution prompt adaptation."""

from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
import pytest

from app.agents.policy_checker import (
    build_image_spatial_context,
    check_policy,
)
from app.schemas.policy_checker import PolicyCheckerOutput
from app.schemas.refund import EvidenceItem


def _make_mock_llm(output: PolicyCheckerOutput) -> MagicMock:
    """Helper to create a mocked BaseChatModel capturing invocations and returning structured output."""
    mock = MagicMock()
    json_text = output.model_dump_json()
    ai_msg = AIMessage(content=f"```json\n{json_text}\n```")
    mock.invoke.return_value = ai_msg
    bound = MagicMock()
    bound.invoke.return_value = ai_msg
    mock.bind_tools.return_value = bound
    mock.with_structured_output.return_value = RunnableLambda(lambda _: output)
    mock.final_output = output
    return mock


def test_build_image_spatial_context_landscape_high_resolution():
    """AC: identifies landscape high-resolution images (e.g. 4000x2000) with landscape, wide/high-resolution tier and wide guidance."""
    # Arrange
    evidence = [
        {
            "filename": "living_room_wide.jpg",
            "width": 4000,
            "height": 2000,
        }
    ]

    # Act
    context = build_image_spatial_context(evidence)

    # Assert
    assert "Evidence Image Spatial Guidance:\n" in context
    assert "- Image 1 (living_room_wide.jpg): 4000x2000 (aspect ratio 2.0, landscape, wide/high-resolution)." in context
    assert (
        "Wide / High-resolution perspective: Evaluate overall item composition, "
        "surrounding packaging condition, complete item integrity, and spatial defect location."
    ) in context


def test_build_image_spatial_context_portrait_orientation():
    """AC: identifies portrait images (e.g. 1080x1920) with portrait orientation."""
    # Arrange
    evidence = [
        {
            "filename": "phone_screenshot.png",
            "width": 1080,
            "height": 1920,
        }
    ]

    # Act
    context = build_image_spatial_context(evidence)

    # Assert
    assert "Evidence Image Spatial Guidance:\n" in context
    assert "- Image 1 (phone_screenshot.png): 1080x1920 (aspect ratio 0.56, portrait, standard)." in context
    assert (
        "Standard perspective: Perform balanced item recognition and defect "
        "localization across product body and immediate packaging."
    ) in context


def test_build_image_spatial_context_macro_close_up():
    """AC: identifies macro/close-up images (e.g. 200x200) with square orientation, macro/close-up tier and macro guidance."""
    # Arrange
    evidence = [
        {
            "filename": "scratch_macro.jpg",
            "width": 200,
            "height": 200,
        }
    ]

    # Act
    context = build_image_spatial_context(evidence)

    # Assert
    assert "Evidence Image Spatial Guidance:\n" in context
    assert "- Image 1 (scratch_macro.jpg): 200x200 (aspect ratio 1.0, square, macro/close-up)." in context
    assert (
        "Macro / Close-up perspective: Focus on micro-defects, surface cracks, "
        "fine texture, serial numbers, or localized hardware flaws."
    ) in context


def test_build_image_spatial_context_standard_resolution():
    """AC: identifies standard images (e.g. 1200x900) with landscape orientation, standard tier and standard guidance."""
    # Arrange
    evidence = [
        {
            "filename": "package_box.jpg",
            "width": 1200,
            "height": 900,
        }
    ]

    # Act
    context = build_image_spatial_context(evidence)

    # Assert
    assert "Evidence Image Spatial Guidance:\n" in context
    assert "- Image 1 (package_box.jpg): 1200x900 (aspect ratio 1.33, landscape, standard)." in context
    assert (
        "Standard perspective: Perform balanced item recognition and defect "
        "localization across product body and immediate packaging."
    ) in context


def test_build_image_spatial_context_empty_none_or_missing_dimensions():
    """AC: returns '' for empty lists, None, or items missing width/height."""
    # Arrange & Act & Assert
    assert build_image_spatial_context(None) == ""
    assert build_image_spatial_context([]) == ""
    assert build_image_spatial_context([{"filename": "nodims.jpg"}]) == ""
    assert build_image_spatial_context([{"filename": "bad1.jpg", "width": 0, "height": 100}]) == ""
    assert build_image_spatial_context([{"filename": "bad2.jpg", "width": 100, "height": -50}]) == ""
    assert build_image_spatial_context([{"filename": "bad3.jpg", "width": None, "height": 800}]) == ""
    assert build_image_spatial_context([{"filename": "bad4.jpg", "width": "invalid", "height": 800}]) == ""
    assert build_image_spatial_context([{"filename": "bad5.jpg", "width": True, "height": 800}]) == ""
    assert build_image_spatial_context([None]) == ""


def test_build_image_spatial_context_multiple_images_numbering():
    """AC: correctly numbers multiple images (1-indexed) in multi-line output."""
    # Arrange
    evidence = [
        {
            "filename": "wide.jpg",
            "width": 4000,
            "height": 2000,
        },
        {
            "filename": "skipped_no_dims.jpg",
            "width": None,
            "height": None,
        },
        {
            "filename": "macro.jpg",
            "width": 300,
            "height": 300,
        },
        {
            "filename": "",  # Missing filename defaults to image_{idx}
            "width": 1200,
            "height": 900,
        },
    ]

    # Act
    context = build_image_spatial_context(evidence)

    # Assert
    assert context.startswith("Evidence Image Spatial Guidance:\n")
    lines = context.strip().split("\n")
    assert len(lines) == 4  # Header + 3 valid images
    assert lines[1].startswith("- Image 1 (wide.jpg): 4000x2000")
    assert lines[2].startswith("- Image 2 (macro.jpg): 300x300")
    assert lines[3].startswith("- Image 3 (image_3): 1200x900")


def test_build_image_spatial_context_filename_fallback():
    """AC: safely resolves filename, defaulting to 'image_{idx}' if missing, empty, or whitespace."""
    # Arrange
    evidence = [
        {"width": 800, "height": 600},  # No filename key
        {"filename": "   ", "width": 1000, "height": 1000},  # Whitespace only
        {"filename": None, "width": 640, "height": 480},  # None filename
    ]

    # Act
    context = build_image_spatial_context(evidence)

    # Assert
    lines = context.strip().split("\n")
    assert lines[1].startswith("- Image 1 (image_1):")
    assert lines[2].startswith("- Image 2 (image_2):")
    assert lines[3].startswith("- Image 3 (image_3):")


def test_build_image_spatial_context_supports_pydantic_evidence_item():
    """AC: handles both Pydantic models (EvidenceItem) and raw dictionary items safely."""
    # Arrange
    item = EvidenceItem(
        storage_key="evidence/ORD-1001/crack.jpg",
        filename="crack_detail.jpg",
        content_type="image/jpeg",
        size_bytes=2048,
        url="https://storage.local/crack.jpg",
        width=400,
        height=400,
    )

    # Act
    context = build_image_spatial_context([item])

    # Assert
    assert "- Image 1 (crack_detail.jpg): 400x400 (aspect ratio 1.0, square, macro/close-up)." in context


def test_check_policy_includes_spatial_guidance_with_image_dimensions():
    """AC: verifies check_policy includes spatial guidance in LLM HumanMessage when evidence with dimensions is provided."""
    # Arrange
    recent_date = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    order = {
        "order_id": "ORD-1001",
        "item": "Ergonomic Office Chair",
        "order_amount": 250.0,
        "delivery_status": "delivered",
        "delivery_date": recent_date,
    }
    evidence = [
        {
            "filename": "armrest_crack.jpg",
            "content_type": "image/jpeg",
            "raw_bytes": b"\xff\xd8\xff\xe0mockjpegdata",
            "width": 3840,
            "height": 2160,
        }
    ]
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Multimodal inspection confirmed structural crack on armrest.",
    )
    mock_llm = _make_mock_llm(expected_output)

    # Act
    result = check_policy(
        category="damaged",
        order=order,
        llm=mock_llm,
        evidence=evidence,
        customer_request_text="Armrest arrived cracked in transit.",
    )

    # Assert
    assert result.policy_status == "pass"
    bound_model = mock_llm.bind_tools.return_value
    assert bound_model.invoke.called
    invoked_messages = bound_model.invoke.call_args[0][0]
    human_msg = next(m for m in invoked_messages if isinstance(m, HumanMessage))

    # HumanMessage content is a list of blocks when image_blocks is present
    assert isinstance(human_msg.content, list)
    prompt_text = human_msg.content[0]["text"]
    assert "Evidence Image Spatial Guidance:\n" in prompt_text
    assert "- Image 1 (armrest_crack.jpg): 3840x2160 (aspect ratio 1.78, landscape, wide/high-resolution)." in prompt_text
    assert "Wide / High-resolution perspective:" in prompt_text
    assert "\n\nAnalyze the situation and provide your determination:" in prompt_text


def test_check_policy_excludes_spatial_guidance_when_dimensions_missing():
    """AC: verifies check_policy excludes spatial guidance and runs without error when evidence lacks dimensions."""
    # Arrange
    recent_date = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    order = {
        "order_id": "ORD-1001",
        "item": "Ergonomic Office Chair",
        "order_amount": 250.0,
        "delivery_status": "delivered",
        "delivery_date": recent_date,
    }
    evidence = [
        {
            "filename": "armrest_crack_legacy.jpg",
            "content_type": "image/jpeg",
            "raw_bytes": b"\xff\xd8\xff\xe0mockjpegdata",
            # width and height omitted
        }
    ]
    expected_output = PolicyCheckerOutput(
        policy_status="pass",
        passed_rules=["refund_window_days", "eligible_delivery_statuses", "max_order_amount"],
        failed_rules=[],
        policy_reasoning="Damage confirmed via legacy image.",
    )
    mock_llm = _make_mock_llm(expected_output)

    # Act
    result = check_policy(
        category="damaged",
        order=order,
        llm=mock_llm,
        evidence=evidence,
        customer_request_text="Armrest arrived cracked in transit.",
    )

    # Assert
    assert result.policy_status == "pass"
    bound_model = mock_llm.bind_tools.return_value
    assert bound_model.invoke.called
    invoked_messages = bound_model.invoke.call_args[0][0]
    human_msg = next(m for m in invoked_messages if isinstance(m, HumanMessage))

    prompt_text = human_msg.content[0]["text"]
    assert "Evidence Image Spatial Guidance:" not in prompt_text
    assert "Analyze the situation and provide your determination:" in prompt_text


def test_check_policy_deterministic_bypass_unaffected():
    """AC: deterministic bypass logic in check_policy remains unchanged and does not invoke the LLM."""
    # Arrange: clear-cut pass for changed_mind within return window
    recent_date = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    order = {
        "order_id": "ORD-1001",
        "item": "Ergonomic Office Chair",
        "order_amount": 100.0,
        "delivery_status": "delivered",
        "delivery_date": recent_date,
    }
    evidence = [
        {
            "filename": "chair.jpg",
            "content_type": "image/jpeg",
            "raw_bytes": b"\xff\xd8\xff\xe0mockjpegdata",
            "width": 1920,
            "height": 1080,
        }
    ]
    mock_llm = MagicMock()

    # Act
    result = check_policy(
        category="changed_mind",
        order=order,
        llm=mock_llm,
        evidence=evidence,
    )

    # Assert: deterministic pass returned immediately without invoking LLM
    assert result.policy_status == "pass"
    mock_llm.invoke.assert_not_called()
    mock_llm.bind_tools.assert_not_called()
