"""Amazon Cognito and OAuth2 JWT authentication provider integration.

Implements pure Python standard library JWT decoding, signature verification,
claims extraction, and test token generation without external third-party JWT dependencies.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from fastapi import HTTPException, status

from app.core.config import get_settings


def _unauthorized_exception(detail: str = "Invalid or expired authentication token") -> HTTPException:
    """Construct an RFC 9457 compliant 401 Unauthorized HTTPException."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "type": "urn:problem:unauthorized",
            "title": "Unauthorized",
            "status": status.HTTP_401_UNAUTHORIZED,
            "detail": detail,
        },
    )


def _base64url_decode(s: str) -> bytes:
    """Decode a base64url-encoded string, automatically handling missing padding."""
    rem = len(s) % 4
    if rem > 0:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _base64url_encode(b: bytes) -> str:
    """Encode bytes into an unpadded base64url string."""
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def decode_jwt(
    token: str,
    secret_key: str | None = None,
    verify_signature: bool = True,
    verify_exp: bool = True,
) -> dict[str, Any]:
    """Decode and validate a JWT bearer token using pure standard library routines.

    Validates:
    - Token format (3 base64url segments separated by dots)
    - Base64url encoding and valid JSON structure
    - HMAC-SHA256 signature when verify_signature=True
    - Expiration claim 'exp' against current timestamp when verify_exp=True
    - Issuer claim 'iss' against Cognito User Pool issuer if configured
    - 'token_use' claim to be 'access' or 'id' if present

    Raises:
        HTTPException: HTTP 401 with RFC 9457 ProblemDetails on any validation failure.
    """
    if not isinstance(token, str):
        raise _unauthorized_exception()

    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            raise _unauthorized_exception()

        header_b64, payload_b64, sig_b64 = parts
        header_bytes = _base64url_decode(header_b64)
        header = json.loads(header_bytes.decode("utf-8"))
        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise _unauthorized_exception()
    except HTTPException:
        raise
    except Exception:
        raise _unauthorized_exception()

    if verify_signature:
        if secret_key is None:
            secret_key = get_settings().jwt_secret_key
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        try:
            actual_sig = _base64url_decode(sig_b64)
        except Exception:
            raise _unauthorized_exception()

        if not hmac.compare_digest(actual_sig, expected_sig):
            raise _unauthorized_exception()

    if verify_exp and "exp" in payload:
        try:
            exp_val = float(payload["exp"])
        except (ValueError, TypeError):
            raise _unauthorized_exception()
        if exp_val < time.time():
            raise _unauthorized_exception()

    settings = get_settings()
    if settings.cognito_user_pool_id:
        expected_iss = f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.cognito_user_pool_id}"
        if payload.get("iss") != expected_iss:
            raise _unauthorized_exception()

    if "token_use" in payload:
        if payload["token_use"] not in ("access", "id"):
            raise _unauthorized_exception()

    return payload


def extract_user_role(payload: dict[str, Any]) -> str:
    """Extract user role ('senior_manager', 'supervisor', or 'agent') from decoded JWT payload claims.

    Maps 'cognito:groups' or 'roles' with hierarchical precedence:
    - Resolves to 'senior_manager' if 'senior_managers', 'senior_manager', or 'admin' is present.
    - Resolves to 'supervisor' if 'supervisors' or 'supervisor' is present.
    - Otherwise defaults to 'agent'.
    """
    raw_groups = payload.get("cognito:groups")
    if raw_groups is None:
        raw_groups = payload.get("roles")
    if raw_groups is None:
        return "agent"

    if isinstance(raw_groups, str):
        groups = [raw_groups]
    elif isinstance(raw_groups, (list, tuple, set)):
        groups = list(raw_groups)
    else:
        return "agent"

    normalized = {str(g).strip().lower() for g in groups}
    if any(mgr_name in normalized for mgr_name in ("senior_managers", "senior_manager", "admin")):
        return "senior_manager"
    if any(supervisor_name in normalized for supervisor_name in ("supervisors", "supervisor")):
        return "supervisor"
    return "agent"


def extract_user_id(payload: dict[str, Any]) -> str:
    """Extract authenticated user ID from decoded JWT payload.

    Reads 'sub', 'cognito:username', or 'username', defaulting to 'anonymous'.
    """
    identity = (
        payload.get("sub")
        or payload.get("cognito:username")
        or payload.get("username")
        or "anonymous"
    )
    return str(identity).strip() or "anonymous"


def create_jwt_token(
    payload: dict[str, Any],
    secret_key: str,
    expires_in: int = 3600,
    algorithm: str = "HS256",
) -> str:
    """Construct a signed base64url JWT token for deterministic offline testing and demo auth."""
    header = {"alg": algorithm, "typ": "JWT"}
    token_payload = dict(payload)
    if "exp" not in token_payload and expires_in is not None:
        token_payload["exp"] = int(time.time()) + expires_in

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(token_payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _base64url_encode(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"
