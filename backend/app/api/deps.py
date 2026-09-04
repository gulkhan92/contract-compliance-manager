"""Shared FastAPI dependencies: DB session, current user, and RBAC.

Every state-changing / data-reading endpoint must depend on `get_current_user`
(or a `require_role(...)` built on it) and must scope its queries by
`current_user.org_id` — never trust an `org_id` passed in a request body or
query string. See docs/CONTRACT_CLM_BUILD_PLAN.md §6.3.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, TokenType, decode_token
from app.db.enums import UserRole
from app.db.models import User
from app.db.session import get_db

_bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: DbSession,
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated.")

    try:
        decoded = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise _unauthorized("Invalid or expired token.") from exc

    user = await db.get(User, decoded.user_id)
    if user is None or not user.is_active or user.org_id != decoded.org_id:
        raise _unauthorized("Invalid or expired token.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(
    *roles: UserRole,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """`Depends(require_role(UserRole.ADMIN))` — 403s any authenticated user
    whose role isn't in `roles`."""

    async def _check(current_user: CurrentUser) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _check
