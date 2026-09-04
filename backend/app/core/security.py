"""Password hashing and JWT issuance/verification.

Two deliberate deviations from the plan's originally specified libraries,
both to avoid shipping a known-broken or known-vulnerable dependency:

- Password hashing uses `bcrypt` directly rather than `passlib[bcrypt]`:
  passlib hasn't been released since 2020 and is incompatible with
  bcrypt>=4.1 (it reads a `bcrypt.__about__.__version__` attribute that no
  longer exists), so `CryptContext.hash(...)` raises at runtime.
- JWTs use `PyJWT` rather than `python-jose`: python-jose unconditionally
  pulls in `python-ecdsa` even when only the `[cryptography]` extra (and
  only HS256, an HMAC algorithm with no ECDSA involved at all) is used, and
  that ecdsa version carries CVE-2024-23342 (a Minerva timing attack) with
  no fix released — the upstream maintainers have declared side-channel
  attacks out of scope. PyJWT has no required dependencies for HS256.
"""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings
from app.db.enums import UserRole

_JWT_ALGORITHM = "HS256"
_BCRYPT_MAX_PASSWORD_BYTES = 72  # bcrypt silently ignores bytes beyond this


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class InvalidTokenError(Exception):
    """A JWT failed signature/expiry verification or has the wrong type."""


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {_BCRYPT_MAX_PASSWORD_BYTES} bytes.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed stored hash (e.g. a seed-data placeholder) — never a match.
        return False


def _create_token(
    *,
    token_type: TokenType,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    role: UserRole,
    expires_delta: timedelta,
) -> tuple[str, str, datetime]:
    """Returns (encoded_token, jti, expires_at)."""
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role.value,
        "type": token_type.value,
        "iat": now,
        "exp": expires_at,
        "jti": jti,
    }
    settings = get_settings()
    encoded = jwt.encode(claims, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)
    return encoded, jti, expires_at


def create_access_token(*, user_id: uuid.UUID, org_id: uuid.UUID, role: UserRole) -> str:
    settings = get_settings()
    token, _jti, _exp = _create_token(
        token_type=TokenType.ACCESS,
        user_id=user_id,
        org_id=org_id,
        role=role,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )
    return token


def create_refresh_token(
    *, user_id: uuid.UUID, org_id: uuid.UUID, role: UserRole
) -> tuple[str, str, datetime]:
    """Returns (encoded_token, jti, expires_at) — the caller persists a hash
    of the token plus its jti/expiry in the `refresh_tokens` table."""
    settings = get_settings()
    return _create_token(
        token_type=TokenType.REFRESH,
        user_id=user_id,
        org_id=org_id,
        role=role,
        expires_delta=timedelta(days=settings.jwt_refresh_token_expire_days),
    )


class DecodedToken:
    def __init__(self, user_id: uuid.UUID, org_id: uuid.UUID, role: UserRole, jti: str) -> None:
        self.user_id = user_id
        self.org_id = org_id
        self.role = role
        self.jti = jti


def decode_token(token: str, *, expected_type: TokenType) -> DecodedToken:
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("Token signature/expiry verification failed.") from exc

    if claims.get("type") != expected_type.value:
        raise InvalidTokenError(f"Expected a {expected_type.value} token.")

    try:
        return DecodedToken(
            user_id=uuid.UUID(claims["sub"]),
            org_id=uuid.UUID(claims["org_id"]),
            role=UserRole(claims["role"]),
            jti=claims["jti"],
        )
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("Token is missing required claims.") from exc
