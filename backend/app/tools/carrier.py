"""Carrier logistics lookup tool for package delivery status and proof-of-delivery verification."""

from typing import Any
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field, field_validator


class CallableStructuredTool(StructuredTool):
    """StructuredTool subclass enabling direct invocation as a Python callable."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute tool directly with positional or keyword arguments."""
        if args and not kwargs:
            if self.args_schema:
                schema_fields = list(self.args_schema.model_fields.keys())
                if len(schema_fields) == 1:
                    return self.invoke({schema_fields[0]: args[0]})
            return self.invoke(args[0] if isinstance(args[0], dict) else {"input": args[0]})
        return self.invoke(kwargs)


class CarrierTrackingInput(BaseModel):
    """Input schema for carrier tracking lookup."""

    tracking_number: str = Field(
        ...,
        min_length=1,
        description="Carrier tracking number to look up.",
    )

    @field_validator("tracking_number")
    @classmethod
    def not_blank(cls, v: str) -> str:
        """Strip surrounding whitespace and ensure tracking number is not blank."""
        if not v or not v.strip():
            raise ValueError("tracking_number cannot be empty or blank")
        return v.strip()


# Representative FedEx shipments covering key delivery states
MOCK_CARRIER_REGISTRY: dict[str, dict[str, Any]] = {
    "FX-987654321": {
        "tracking_number": "FX-987654321",
        "carrier": "FedEx",
        "delivery_status": "delivered",
        "delivery_date": "2026-09-12 14:22:00",
        "delivery_address": "123 Market St, San Francisco, CA 94105",
        "proof_of_delivery_photo_available": True,
        "events": [
            {
                "timestamp": "2026-09-10 08:30:00",
                "location": "Memphis, TN",
                "status": "picked_up",
                "description": "Package received by carrier at sorting facility.",
            },
            {
                "timestamp": "2026-09-11 14:15:00",
                "location": "Oakland, CA",
                "status": "in_transit",
                "description": "Departed regional distribution hub.",
            },
            {
                "timestamp": "2026-09-12 08:00:00",
                "location": "San Francisco, CA",
                "status": "out_for_delivery",
                "description": "Out for delivery with courier.",
            },
            {
                "timestamp": "2026-09-12 14:22:00",
                "location": "San Francisco, CA",
                "status": "delivered",
                "description": "Package delivered to front porch. Signature and photo captured.",
            },
        ],
    },
    "FX-112233445": {
        "tracking_number": "FX-112233445",
        "carrier": "FedEx",
        "delivery_status": "in_transit",
        "delivery_date": None,
        "delivery_address": "456 Elm St, Austin, TX 78701",
        "proof_of_delivery_photo_available": False,
        "events": [
            {
                "timestamp": "2026-09-20 09:00:00",
                "location": "Dallas, TN",
                "status": "picked_up",
                "description": "Package picked up at origin terminal.",
            },
            {
                "timestamp": "2026-09-21 16:45:00",
                "location": "Waco, TX",
                "status": "in_transit",
                "description": "In transit to destination facility.",
            },
        ],
    },
    "FX-998877665": {
        "tracking_number": "FX-998877665",
        "carrier": "FedEx",
        "delivery_status": "delivered",
        "delivery_date": "2026-09-14 10:15:00",
        "delivery_address": "789 Pine St, Seattle, WA 98101",
        "proof_of_delivery_photo_available": False,
        "events": [
            {
                "timestamp": "2026-09-12 11:00:00",
                "location": "Portland, OR",
                "status": "picked_up",
                "description": "Package received by carrier.",
            },
            {
                "timestamp": "2026-09-13 18:20:00",
                "location": "Tacoma, WA",
                "status": "in_transit",
                "description": "In transit to local facility.",
            },
            {
                "timestamp": "2026-09-14 10:15:00",
                "location": "Seattle, WA",
                "status": "delivered",
                "description": "Delivered to mailroom without photo.",
            },
        ],
    },
    "FX-554433221": {
        "tracking_number": "FX-554433221",
        "carrier": "FedEx",
        "delivery_status": "out_for_delivery",
        "delivery_date": None,
        "delivery_address": "321 Oak St, Chicago, IL 60601",
        "proof_of_delivery_photo_available": False,
        "events": [
            {
                "timestamp": "2026-09-21 07:15:00",
                "location": "Chicago, IL",
                "status": "out_for_delivery",
                "description": "Out for delivery with courier.",
            },
        ],
    },
    "FX-667788990": {
        "tracking_number": "FX-667788990",
        "carrier": "FedEx",
        "delivery_status": "exception",
        "delivery_date": None,
        "delivery_address": "654 Maple St, Denver, CO 80202",
        "proof_of_delivery_photo_available": False,
        "events": [
            {
                "timestamp": "2026-09-19 14:00:00",
                "location": "Denver, CO",
                "status": "exception",
                "description": "Delivery exception: Security access code required. Held at facility.",
            },
        ],
    },
    # Order-specific mock tracking numbers
    "TRK-1001": {
        "tracking_number": "TRK-1001",
        "carrier": "FedEx",
        "delivery_status": "delivered",
        "delivery_date": "2026-09-12 14:22:00",
        "delivery_address": "123 Market St, San Francisco, CA 94105",
        "proof_of_delivery_photo_available": True,
        "events": [
            {
                "timestamp": "2026-09-12 14:22:00",
                "location": "San Francisco, CA",
                "status": "delivered",
                "description": "Package delivered with photo.",
            },
        ],
    },
    "TRK-1002": {
        "tracking_number": "TRK-1002",
        "carrier": "FedEx",
        "delivery_status": "delivered",
        "delivery_date": "2026-09-08 11:00:00",
        "delivery_address": "550 Battery St, San Francisco, CA 94111",
        "proof_of_delivery_photo_available": True,
        "events": [
            {
                "timestamp": "2026-09-08 11:00:00",
                "location": "San Francisco, CA",
                "status": "delivered",
                "description": "Delivered to front door.",
            },
        ],
    },
    "TRK-1003": {
        "tracking_number": "TRK-1003",
        "carrier": "FedEx",
        "delivery_status": "delivered",
        "delivery_date": "2026-09-04 15:45:00",
        "delivery_address": "880 Broadway, New York, NY 10003",
        "proof_of_delivery_photo_available": False,
        "events": [
            {
                "timestamp": "2026-09-04 15:45:00",
                "location": "New York, NY",
                "status": "delivered",
                "description": "Delivered to reception desk.",
            },
        ],
    },
    "TRK-1004": {
        "tracking_number": "TRK-1004",
        "carrier": "FedEx",
        "delivery_status": "delivered",
        "delivery_date": "2026-08-05 11:30:00",
        "delivery_address": "100 Tech Way, Boston, MA 02110",
        "proof_of_delivery_photo_available": False,
        "events": [
            {
                "timestamp": "2026-08-05 11:30:00",
                "location": "Boston, MA",
                "status": "delivered",
                "description": "Delivered to recipient mailbox.",
            },
        ],
    },
    "TRK-1005": {
        "tracking_number": "TRK-1005",
        "carrier": "FedEx",
        "delivery_status": "in_transit",
        "delivery_date": None,
        "delivery_address": "500 Innovation Blvd, Austin, TX 78701",
        "proof_of_delivery_photo_available": False,
        "events": [
            {
                "timestamp": "2026-09-19 10:00:00",
                "location": "Dallas, TX",
                "status": "in_transit",
                "description": "Departed FedEx location.",
            },
        ],
    },
    "TRK-1007": {
        "tracking_number": "TRK-1007",
        "carrier": "FedEx",
        "delivery_status": "delivered",
        "delivery_date": "2026-09-16 13:00:00",
        "delivery_address": "250 Fifth Ave, New York, NY 10001",
        "proof_of_delivery_photo_available": True,
        "events": [
            {
                "timestamp": "2026-09-16 13:00:00",
                "location": "New York, NY",
                "status": "delivered",
                "description": "Delivered to front door with photo proof.",
            },
        ],
    },
}


def _make_invalid_carrier_response(tracking_number: str = "") -> dict[str, Any]:
    """Construct standard invalid response payload for blank or missing tracking number."""
    return {
        "found": False,
        "tracking_number": tracking_number,
        "error": "Tracking number must not be empty or blank.",
        "carrier": "FedEx",
        "delivery_status": "invalid",
        "delivery_date": None,
        "delivery_address": None,
        "proof_of_delivery_photo_available": False,
        "events": [],
    }


def _handle_carrier_validation_error(err: Any) -> dict[str, Any]:
    """Handle LangChain / Pydantic validation error gracefully during tool invocation."""
    input_val = ""
    if hasattr(err, "errors"):
        errors = err.errors()
        if errors and "input" in errors[0]:
            val = errors[0]["input"]
            if isinstance(val, dict):
                input_val = str(val.get("tracking_number", ""))
            elif val is not None:
                input_val = str(val)
    return _make_invalid_carrier_response(input_val)


@tool("query_carrier_tracking", args_schema=CarrierTrackingInput)
def query_carrier_tracking(tracking_number: str) -> dict[str, Any]:
    """Query carrier tracking information, delivery status, dates, and proof-of-delivery photos.

    Args:
        tracking_number: The carrier tracking number to look up (e.g. 'FX-987654321', 'TRK-1004').

    Returns:
        Structured dictionary containing shipment status, delivery date, photo availability,
        and chronological tracking events.
    """
    if not tracking_number or not isinstance(tracking_number, str) or not tracking_number.strip():
        return _make_invalid_carrier_response(str(tracking_number) if tracking_number is not None else "")

    clean_tracking = tracking_number.strip()
    lookup_key = clean_tracking.upper()

    record = MOCK_CARRIER_REGISTRY.get(lookup_key)
    if record is not None:
        return {
            "found": True,
            "tracking_number": record["tracking_number"],
            "carrier": record.get("carrier", "FedEx"),
            "delivery_status": record["delivery_status"],
            "delivery_date": record["delivery_date"],
            "delivery_address": record["delivery_address"],
            "proof_of_delivery_photo_available": record["proof_of_delivery_photo_available"],
            "events": record.get("events", []),
            "error": None,
        }

    return {
        "found": False,
        "tracking_number": clean_tracking,
        "error": f"Tracking number '{clean_tracking}' not found.",
        "carrier": "FedEx",
        "delivery_status": "unknown",
        "delivery_date": None,
        "delivery_address": None,
        "proof_of_delivery_photo_available": False,
        "events": [],
    }


# Ensure tool supports both direct Python call syntax and LangChain Runnable .invoke()
query_carrier_tracking.__class__ = CallableStructuredTool
query_carrier_tracking.handle_validation_error = _handle_carrier_validation_error
