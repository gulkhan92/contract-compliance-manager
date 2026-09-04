from datetime import timedelta
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenType, _create_token, create_access_token, hash_password
from app.db.enums import UserRole
from app.db.models import Organization, User


async def _register(
    client: AsyncClient, *, org_name: str = "Acme Corp", email: str = "admin@example.com"
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "org_name": org_name,
            "email": email,
            "password": "correct horse battery staple",
            "full_name": "Ada Admin",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, str], response.json())


@pytest.mark.asyncio
async def test_register_creates_org_and_admin_user(client: AsyncClient) -> None:
    body = await _register(client)

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "refresh_token" in client.cookies


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    await _register(client, email="dup@example.com")

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Other Corp",
            "email": "dup@example.com",
            "password": "another password here",
            "full_name": "Someone Else",
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    await _register(client, email="login-ok@example.com")

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "login-ok@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


@pytest.mark.asyncio
async def test_login_unsuccessful_wrong_password(client: AsyncClient) -> None:
    await _register(client, email="wrongpw@example.com")

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpw@example.com", "password": "not the right password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_unsuccessful_unknown_email(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever it is"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_current_user(client: AsyncClient) -> None:
    await _register(client, org_name="Beta LLC", email="me@example.com")
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "me@example.com", "password": "correct horse battery staple"},
        )
    ).json()["access_token"]

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["role"] == "admin"


@pytest.mark.asyncio
async def test_expired_access_token_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = Organization(name="Expiry Test Org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email="expired@example.com",
        hashed_password=hash_password("irrelevant password"),
        role=UserRole.ADMIN,
        full_name="Expired Token User",
    )
    db_session.add(user)
    await db_session.flush()

    # _create_token is "private" but constructing an already-expired token
    # is otherwise only possible by waiting out a real expiry window.
    expired_token, _jti, _exp = _create_token(
        token_type=TokenType.ACCESS,
        user_id=user.id,
        org_id=org.id,
        role=user.role,
        expires_delta=timedelta(minutes=-1),
    )

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_endpoint_allows_admin(client: AsyncClient) -> None:
    body = await _register(client, email="admin-ok@example.com")

    response = await client.get(
        "/api/v1/admin/ping", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_endpoint_wrong_role_forbidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = Organization(name="Viewer Org")
    db_session.add(org)
    await db_session.flush()
    viewer = User(
        org_id=org.id,
        email="viewer@example.com",
        hashed_password=hash_password("irrelevant password"),
        role=UserRole.VIEWER,
        full_name="Vera Viewer",
    )
    db_session.add(viewer)
    await db_session.flush()

    token = create_access_token(user_id=viewer.id, org_id=org.id, role=viewer.role)

    response = await client.get(
        "/api/v1/admin/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_rejects_reuse(client: AsyncClient) -> None:
    await _register(client, email="refresh@example.com")
    original_refresh_cookie = client.cookies["refresh_token"]

    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 200
    new_access_token = response.json()["access_token"]
    assert new_access_token

    # The rotated-out token must be rejected if replayed. Set the Cookie
    # header directly rather than httpx's client-level cookie jar (which
    # now holds the rotated-in token).
    replay_response = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={original_refresh_cookie}"},
    )
    assert replay_response.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    body = await _register(client, email="logout@example.com")

    logout_response = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert logout_response.status_code == 204

    refresh_response = await client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 401


@pytest.mark.asyncio
async def test_cross_org_token_tampering_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A token's org_id claim must match the user's actual org — the
    mechanism underpinning cross-org data isolation (§6.3): every query is
    scoped by `current_user.org_id`, so a token that can't pass this check
    can never see another org's data. Full resource-level cross-org
    isolation gets its own test once org-scoped resource endpoints exist
    (Phase 6+)."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    user_in_org_a = User(
        org_id=org_a.id,
        email="a@example.com",
        hashed_password=hash_password("irrelevant password"),
        role=UserRole.ADMIN,
        full_name="Org A Admin",
    )
    db_session.add(user_in_org_a)
    await db_session.flush()

    # Simulates a stale/tampered token whose org_id no longer matches the
    # user's real org — get_current_user must reject it, not silently trust
    # the claim.
    tampered_token = create_access_token(
        user_id=user_in_org_a.id, org_id=org_b.id, role=user_in_org_a.role
    )

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limited_after_repeated_attempts(client: AsyncClient) -> None:
    await _register(client, email="ratelimit@example.com")

    responses = [
        await client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit@example.com", "password": "wrong password"},
        )
        for _ in range(6)
    ]

    assert responses[-1].status_code == 429
