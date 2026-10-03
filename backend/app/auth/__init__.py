"""Authentication and role-based access control (RBAC) package."""

from app.auth.jwt import (
    create_jwt_token,
    decode_jwt,
    extract_user_id,
    extract_user_role,
)
from app.auth.rbac import (
    DEFAULT_ROLE,
    UserRole,
    get_approval_limit_for_role,
    get_current_user_identity,
    get_current_user_role,
    require_supervisor_role,
)
from app.policy.schema import DEFAULT_ROLE_APPROVAL_LIMITS

__all__ = [
    "DEFAULT_ROLE",
    "DEFAULT_ROLE_APPROVAL_LIMITS",
    "UserRole",
    "create_jwt_token",
    "decode_jwt",
    "extract_user_id",
    "extract_user_role",
    "get_approval_limit_for_role",
    "get_current_user_identity",
    "get_current_user_role",
    "require_supervisor_role",
]
