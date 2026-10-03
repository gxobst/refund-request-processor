"""Role-Based Access Control (RBAC) dependencies and utilities."""

from typing import Literal
from fastapi import Depends, HTTPException, Request, status

UserRole = Literal["agent", "supervisor"]
DEFAULT_ROLE: UserRole = "agent"


def get_current_user_role(request: Request) -> str:
    """Extract and normalize user role from incoming X-User-Role HTTP header.

    Trims leading/trailing whitespace and converts to lowercase.
    Defaults to 'agent' when absent, empty, or whitespace-only.
    """
    raw_role = request.headers.get("X-User-Role", "")
    normalized = raw_role.strip().lower()
    if not normalized:
        return DEFAULT_ROLE
    return normalized


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
