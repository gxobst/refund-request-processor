"""Unit tests for carrier tracking lookup tool."""

import pytest
from pydantic import ValidationError

from app.tools.carrier import (
    CarrierTrackingInput,
    query_carrier_tracking,
)


def test_carrier_tracking_input_schema_validation():
    """Verify CarrierTrackingInput validates non-blank strings and rejects empty/blank inputs."""
    # Arrange & Act: valid input
    model = CarrierTrackingInput(tracking_number="  FX-987654321  ")

    # Assert: stripped whitespace
    assert model.tracking_number == "FX-987654321"

    # Act & Assert: empty string
    with pytest.raises(ValidationError):
        CarrierTrackingInput(tracking_number="")

    # Act & Assert: whitespace-only string
    with pytest.raises(ValidationError):
        CarrierTrackingInput(tracking_number="   ")


def test_query_carrier_tracking_delivered_with_photo():
    """AC 1200: Verify query_carrier_tracking returns valid shipment details for known delivered tracking number with photo proof."""
    # Arrange
    tracking_number = "FX-987654321"

    # Act: direct call
    result = query_carrier_tracking(tracking_number=tracking_number)

    # Assert
    assert result["found"] is True
    assert result["tracking_number"] == "FX-987654321"
    assert result["carrier"] == "FedEx"
    assert result["delivery_status"] == "delivered"
    assert result["delivery_date"] is not None
    assert result["delivery_address"] is not None
    assert result["proof_of_delivery_photo_available"] is True
    assert len(result["events"]) > 0
    assert result["error"] is None


def test_query_carrier_tracking_in_transit_without_photo():
    """AC 1201: Verify query_carrier_tracking returns valid shipment details for known in-transit tracking number without photo."""
    # Arrange
    tracking_number = "FX-112233445"

    # Act
    result = query_carrier_tracking(tracking_number)

    # Assert
    assert result["found"] is True
    assert result["tracking_number"] == "FX-112233445"
    assert result["carrier"] == "FedEx"
    assert result["delivery_status"] == "in_transit"
    assert result["delivery_date"] is None
    assert result["proof_of_delivery_photo_available"] is False
    assert len(result["events"]) > 0
    assert result["error"] is None


def test_query_carrier_tracking_other_states():
    """Verify carrier tracking tool accurately returns delivered without photo, out_for_delivery, and exception statuses."""
    # Delivered without photo
    res_no_photo = query_carrier_tracking("FX-998877665")
    assert res_no_photo["found"] is True
    assert res_no_photo["delivery_status"] == "delivered"
    assert res_no_photo["proof_of_delivery_photo_available"] is False

    # Out for delivery
    res_ofd = query_carrier_tracking("FX-554433221")
    assert res_ofd["found"] is True
    assert res_ofd["delivery_status"] == "out_for_delivery"
    assert res_ofd["proof_of_delivery_photo_available"] is False

    # Exception
    res_exc = query_carrier_tracking("FX-667788990")
    assert res_exc["found"] is True
    assert res_exc["delivery_status"] == "exception"
    assert res_exc["proof_of_delivery_photo_available"] is False


def test_query_carrier_tracking_not_found():
    """AC 1202: Verify query_carrier_tracking returns structured not-found response for non-existent tracking number."""
    # Arrange
    unknown_trk = "FX-000000000"

    # Act
    result = query_carrier_tracking(tracking_number=unknown_trk)

    # Assert
    assert result["found"] is False
    assert result["tracking_number"] == unknown_trk
    assert result["error"] == f"Tracking number '{unknown_trk}' not found."
    assert result["carrier"] == "FedEx"
    assert result["delivery_status"] == "unknown"
    assert result["delivery_date"] is None
    assert result["delivery_address"] is None
    assert result["proof_of_delivery_photo_available"] is False
    assert result["events"] == []


def test_query_carrier_tracking_whitespace_and_case_insensitivity():
    """AC 1203: Verify query_carrier_tracking strips surrounding whitespace and performs case-insensitive lookup."""
    # Arrange
    raw_input = "  fx-987654321  "

    # Act
    result = query_carrier_tracking(raw_input)

    # Assert
    assert result["found"] is True
    assert result["tracking_number"] == "FX-987654321"
    assert result["delivery_status"] == "delivered"
    assert result["proof_of_delivery_photo_available"] is True


def test_query_carrier_tracking_empty_and_whitespace_handling():
    """AC 1204: Verify query_carrier_tracking handles empty or whitespace-only strings without raising exceptions."""
    # Act: empty string
    empty_res = query_carrier_tracking("")
    assert empty_res["found"] is False
    assert empty_res["tracking_number"] == ""
    assert empty_res["error"] == "Tracking number must not be empty or blank."
    assert empty_res["carrier"] == "FedEx"
    assert empty_res["delivery_status"] == "invalid"
    assert empty_res["delivery_date"] is None
    assert empty_res["delivery_address"] is None
    assert empty_res["proof_of_delivery_photo_available"] is False
    assert empty_res["events"] == []

    # Act: whitespace string
    ws_res = query_carrier_tracking("   ")
    assert ws_res["found"] is False
    assert ws_res["tracking_number"] == "   "
    assert ws_res["error"] == "Tracking number must not be empty or blank."
    assert ws_res["delivery_status"] == "invalid"


def test_query_carrier_tracking_langchain_metadata_and_invoke():
    """AC 1205: Verify LangChain tool metadata and invocation via query_carrier_tracking.invoke."""
    # Metadata assertion
    assert query_carrier_tracking.name == "query_carrier_tracking"
    assert "tracking" in query_carrier_tracking.description.lower()
    assert query_carrier_tracking.args_schema == CarrierTrackingInput

    # Act: invoke with dictionary
    invoke_res = query_carrier_tracking.invoke({"tracking_number": "FX-987654321"})
    assert invoke_res["found"] is True
    assert invoke_res["delivery_status"] == "delivered"

    # Act: invoke with empty string handled gracefully via handle_validation_error
    invoke_empty = query_carrier_tracking.invoke({"tracking_number": ""})
    assert invoke_empty["found"] is False
    assert invoke_empty["delivery_status"] == "invalid"
    assert invoke_empty["error"] == "Tracking number must not be empty or blank."

    # Act: invoke with whitespace string handled gracefully
    invoke_ws = query_carrier_tracking.invoke({"tracking_number": "   "})
    assert invoke_ws["found"] is False
    assert invoke_ws["delivery_status"] == "invalid"
    assert invoke_ws["error"] == "Tracking number must not be empty or blank."


def test_query_carrier_tracking_trk_1010():
    """Verify query_carrier_tracking('TRK-1010') returns found=True, carrier='FedEx', and proof_of_delivery_photo_available=True."""
    result = query_carrier_tracking("TRK-1010")
    assert result["found"] is True
    assert result["tracking_number"] == "TRK-1010"
    assert result["carrier"] == "FedEx"
    assert result["delivery_status"] == "delivered"
    assert result["proof_of_delivery_photo_available"] is True
