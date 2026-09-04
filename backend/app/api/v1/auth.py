import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import (
    InvalidTokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.enums import UserRole
from app.db.models import Organization, RefreshToken, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from app.services.audit import write_audit_log

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "refresh_token"


def _refresh_cookie_path() -> str:
    return f"{get_settings().api_v1_prefix}/auth"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    settings = get_settings()
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.environment != "development",
        samesite="strict",
        path=_refresh_cookie_path(),
        expires=expires_at,
    )


async def _issue_tokens(db: DbSession, response: Response, user: User) -> TokenResponse:
    access_token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    refresh_token, _jti, expires_at = create_refresh_token(
        user_id=user.id, org_id=user.org_id, role=user.role
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_token(refresh_token),
            expires_at=expires_at,
        )
    )
    await db.flush()
    _set_refresh_cookie(response, refresh_token, expires_at)
    return TokenResponse(access_token=access_token)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request,  # noqa: ARG001 — required by slowapi to key-off the client IP
    body: RegisterRequest,
    db: DbSession,
    response: Response,
) -> TokenResponse:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    org = Organization(name=body.org_name)
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=UserRole.ADMIN,
        full_name=body.full_name,
    )
    db.add(user)
    await db.flush()

    await write_audit_log(
        db,
        org_id=org.id,
        user_id=user.id,
        action="user.register",
        entity_type="user",
        entity_id=user.id,
    )

    tokens = await _issue_tokens(db, response, user)
    await db.commit()
    return tokens


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,  # noqa: ARG001
    body: LoginRequest,
    db: DbSession,
    response: Response,
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    valid_password = user is not None and verify_password(body.password, user.hashed_password)
    if user is None or not user.is_active or not valid_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password."
        )

    await write_audit_log(
        db,
        org_id=user.org_id,
        user_id=user.id,
        action="user.login",
        entity_type="user",
        entity_id=user.id,
    )

    tokens = await _issue_tokens(db, response, user)
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    db: DbSession,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE_NAME),
) -> TokenResponse:
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token.")

    try:
        decoded = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token."
        ) from exc

    token_hash = _hash_token(refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    stored = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if (
        stored is None
        or stored.revoked_at is not None
        or stored.expires_at.replace(tzinfo=UTC) < now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token."
        )

    user = await db.get(User, decoded.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")

    # Rotate: revoke the presented token before issuing its replacement.
    stored.revoked_at = now
    await db.flush()

    tokens = await _issue_tokens(db, response, user)
    await db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE_NAME),
) -> None:
    if refresh_token is not None:
        token_hash = _hash_token(refresh_token)
        result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        stored = result.scalar_one_or_none()
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            await db.flush()

    await write_audit_log(
        db,
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="user.logout",
        entity_type="user",
        entity_id=current_user.id,
    )
    await db.commit()

    response.delete_cookie(_REFRESH_COOKIE_NAME, path=_refresh_cookie_path())


@router.get("/me", response_model=UserPublic)
async def me(current_user: CurrentUser) -> User:
    return current_user
