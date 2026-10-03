"""Policy configuration API endpoints."""

from typing import Any
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.policy.loader import get_active_policies, update_category_policy
from app.policy.schema import (
    CategoryPolicyUpdate,
    PolicyItemResponse,
    RefundCategory,
)
from app.services.broadcaster import broadcaster

router = APIRouter(prefix="/policies", tags=["policies"])

VALID_CATEGORIES: list[str] = [c.value for c in RefundCategory]


@router.get(
    "",
    response_model=list[PolicyItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List active refund policy rules for all categories",
)
async def list_policies() -> list[PolicyItemResponse]:
    """Retrieve active policy rules across all 5 refund categories."""
    active_config = get_active_policies()
    results: list[PolicyItemResponse] = []
    for cat in VALID_CATEGORIES:
        policy = getattr(active_config, cat)
        results.append(
            PolicyItemResponse(
                category=cat,
                return_window_days=policy.return_window_days,
                max_refund_amount=policy.max_refund_amount,
                auto_approve_threshold=policy.auto_approve_threshold,
                requires_proof=policy.requires_proof,
                eligible_delivery_statuses=policy.eligible_delivery_statuses,
                refund_window_days=policy.refund_window_days,
                max_order_amount=policy.max_order_amount,
            )
        )
    return results


@router.put(
    "/{category}",
    response_model=PolicyItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Update policy configuration for a specific refund category",
)
async def update_policy(category: str, request: Request) -> Any:
    """Update active thresholds and rules for a specified refund category.

    Returns RFC 9457 ProblemDetails (HTTP 404) if category is unknown.
    Returns RFC 9457 ValidationProblemDetails (HTTP 422) if parameters fail validation.
    """
    normalized_category = str(category).strip().lower()
    if normalized_category not in VALID_CATEGORIES:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": (
                    f"Refund category '{category}' is not valid. "
                    f"Valid categories: {', '.join(VALID_CATEGORIES)}."
                ),
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "urn:problem:validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "Invalid JSON payload.",
                "instance": request.url.path,
                "invalidParams": [{"name": "body", "reason": "Expected valid JSON body"}],
            },
            media_type="application/problem+json",
        )

    if not isinstance(body, dict):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "urn:problem:validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "Request body must be a JSON object.",
                "instance": request.url.path,
                "invalidParams": [{"name": "body", "reason": "Request body must be a JSON object"}],
            },
            media_type="application/problem+json",
        )

    try:
        update_model = CategoryPolicyUpdate.model_validate(body)
    except ValidationError as e:
        invalid_params = []
        for err in e.errors():
            loc = err.get("loc", [])
            field_parts = [str(p) for p in loc if str(p) != "body"]
            name = ".".join(field_parts) if field_parts else "unknown"
            reason = err.get("msg", "Validation failed")
            invalid_params.append({"name": name, "reason": reason})

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "urn:problem:validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "One or more fields in the request body failed validation.",
                "instance": request.url.path,
                "invalidParams": invalid_params,
            },
            media_type="application/problem+json",
        )

    try:
        updated_policy = update_category_policy(normalized_category, update_model)
    except KeyError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "urn:problem:not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Refund category '{category}' not found.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )
    except ValidationError as e:
        invalid_params = []
        for err in e.errors():
            loc = err.get("loc", [])
            field_parts = [str(p) for p in loc if str(p) != "body"]
            name = ".".join(field_parts) if field_parts else "unknown"
            reason = err.get("msg", "Validation failed")
            invalid_params.append({"name": name, "reason": reason})

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "urn:problem:validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "One or more fields in the request body failed validation.",
                "instance": request.url.path,
                "invalidParams": invalid_params,
            },
            media_type="application/problem+json",
        )

    response_item = PolicyItemResponse(
        category=normalized_category,
        return_window_days=updated_policy.return_window_days,
        max_refund_amount=updated_policy.max_refund_amount,
        auto_approve_threshold=updated_policy.auto_approve_threshold,
        requires_proof=updated_policy.requires_proof,
        eligible_delivery_statuses=updated_policy.eligible_delivery_statuses,
        refund_window_days=updated_policy.refund_window_days,
        max_order_amount=updated_policy.max_order_amount,
    )
    await broadcaster.publish("policy_update", response_item.model_dump())
    return response_item
