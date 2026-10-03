"""Authentication and role-based access control (RBAC) package."""

from app.auth.rbac import (
    DEFAULT_ROLE,
    UserRole,
    get_current_user_role,
    require_supervisor_role,
)

__all__ = [
    "DEFAULT_ROLE",
    "UserRole",
    "get_current_user_role",
    "require_supervisor_role",
]
