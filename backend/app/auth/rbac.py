"""Role-Based Access Control (RBAC) dependencies and utilities."""

from typing import Literal
from fastapi import Depends, HTTPException, Request, status

from app.auth.jwt import decode_jwt, extract_user_id, extract_user_role
from app.core.config import get_settings

UserRole = Literal["agent", "supervisor"]
DEFAULT_ROLE: UserRole = "agent"


def get_current_user_role(request: Request) -> str:
    """Extract and normalize user role from Authorization Bearer JWT or incoming X-User-Role HTTP header.

    If an Authorization header is present:
    - Validates Bearer token using decode_jwt and returns mapped role ('supervisor' or 'agent').
    - Raises HTTP 401 Unauthorized ProblemDetails if token is invalid, expired, or malformed.

    If no Authorization header is present:
    - If settings.auth_require_jwt is True, raises HTTP 401 Unauthorized ProblemDetails.
    - Otherwise, falls back cleanly to X-User-Role header (defaulting to 'agent').
    """
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header:
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            try:
                payload = decode_jwt(token)
            except HTTPException as exc:
                if isinstance(exc.detail, dict) and "instance" not in exc.detail:
                    exc.detail["instance"] = request.url.path
                raise
            return extract_user_role(payload)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "urn:problem:unauthorized",
                "title": "Unauthorized",
                "status": status.HTTP_401_UNAUTHORIZED,
                "detail": "Invalid or expired authentication token",
                "instance": request.url.path,
            },
        )

    if get_settings().auth_require_jwt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "urn:problem:unauthorized",
                "title": "Unauthorized",
                "status": status.HTTP_401_UNAUTHORIZED,
                "detail": "Authorization header required",
                "instance": request.url.path,
            },
        )

    raw_role = request.headers.get("X-User-Role", "")
    normalized = raw_role.strip().lower()
    if not normalized:
        return DEFAULT_ROLE
    return normalized


def get_current_user_identity(request: Request) -> str:
    """Extract authenticated user identity from Authorization Bearer JWT or X-User-Id header.

    If an Authorization header is present:
    - Validates Bearer token and returns user ID (sub, cognito:username, or username).
    - Raises HTTP 401 Unauthorized ProblemDetails if token is invalid or expired.

    If no Authorization header is present:
    - Falls back to X-User-Id header.
    - If absent or empty, falls back to normalized X-User-Role or 'agent'.
    """
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header:
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            try:
                payload = decode_jwt(token)
            except HTTPException as exc:
                if isinstance(exc.detail, dict) and "instance" not in exc.detail:
                    exc.detail["instance"] = request.url.path
                raise
            return extract_user_id(payload)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "urn:problem:unauthorized",
                "title": "Unauthorized",
                "status": status.HTTP_401_UNAUTHORIZED,
                "detail": "Invalid or expired authentication token",
                "instance": request.url.path,
            },
        )

    user_id = request.headers.get("X-User-Id", "").strip()
    if user_id:
        return user_id

    role = request.headers.get("X-User-Role", "").strip().lower()
    return role if role in ("supervisor", "agent") else DEFAULT_ROLE


def require_supervisor_role(
    role: str = Depends(get_current_user_role),
    request: Request = None,
) -> str:
    """FastAPI dependency verifying that the caller has 'supervisor' role.

    Raises HTTP 403 Forbidden with RFC 9457 ProblemDetails if the role is not 'supervisor'.
    """
    if role != "supervisor":
        path = request.url.path if request is not None else ""
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "urn:problem:forbidden",
                "title": "Forbidden",
                "status": status.HTTP_403_FORBIDDEN,
                "detail": "Supervisor role required to perform manual overrides.",
                "instance": path,
            },
        )
    return role
