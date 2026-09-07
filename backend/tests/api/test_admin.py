import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.enums import ContractStatus, ExtractionJobStatus, LLMProviderName, UserRole
from app.db.models import AuditLog, Contract, ExtractionJob, Organization, User
from app.services.llm import quota


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_org_and_admin(
    db_session: AsyncSession, *, org_name: str, email: str
) -> tuple[Organization, User]:
    org = Organization(name=org_name)
    db_session.add(org)
    await db_session.flush()
    admin = User(
        org_id=org.id,
        email=email,
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        full_name="Org Admin",
    )
    db_session.add(admin)
    await db_session.flush()
    return org, admin


@pytest.mark.asyncio
async def test_llm_usage_requires_admin_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, _admin = await _make_org_and_admin(db_session, org_name="Acme", email="usage1@example.com")
    legal_ops = User(
        org_id=org.id,
        email="legalops-usage@example.com",
        hashed_password="irrelevant",
        role=UserRole.LEGAL_OPS,
        full_name="Legal Ops",
    )
    db_session.add(legal_ops)
    await db_session.flush()

    token = create_access_token(user_id=legal_ops.id, org_id=org.id, role=UserRole.LEGAL_OPS)
    response = await client.get("/api/v1/admin/llm-usage", headers=_auth_headers(token))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_llm_usage_reflects_recorded_usage(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="usage2@example.com")
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    # Explicitly unconfigured, not just ambient: this assertion is
    # specifically testing "no key configured -> no headroom" behavior for
    # Gemini, which must hold regardless of whatever real GEMINI_API_KEY
    # this test suite happens to run against.
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    await quota.record_usage(db_session, LLMProviderName.GROQ, tokens=500)

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.get("/api/v1/admin/llm-usage", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    groq_entry = next(entry for entry in body if entry["provider"] == "groq")
    assert groq_entry["requests_used"] == 1
    assert groq_entry["tokens_used"] == 500
    assert groq_entry["has_headroom"] is True

    gemini_entry = next(entry for entry in body if entry["provider"] == "gemini")
    assert gemini_entry["requests_used"] == 0
    assert gemini_entry["has_headroom"] is False


@pytest.mark.asyncio
async def test_extraction_retry_requires_admin_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, _admin = await _make_org_and_admin(db_session, org_name="Acme", email="retry1@example.com")
    legal_ops = User(
        org_id=org.id,
        email="legalops-retry@example.com",
        hashed_password="irrelevant",
        role=UserRole.LEGAL_OPS,
        full_name="Legal Ops",
    )
    db_session.add(legal_ops)
    await db_session.flush()

    token = create_access_token(user_id=legal_ops.id, org_id=org.id, role=UserRole.LEGAL_OPS)
    response = await client.post("/api/v1/admin/extraction/retry", headers=_auth_headers(token))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_extraction_retry_reports_still_queued_without_provider_headroom(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="retry2@example.com")
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    contract = Contract(
        org_id=org.id,
        uploaded_by=admin.id,
        title="Stuck Contract",
        original_filename="stuck.pdf",
        storage_path="storage/stuck.pdf",
        file_hash="c" * 64,
        status=ContractStatus.PROCESSING,
    )
    db_session.add(contract)
    await db_session.flush()
    db_session.add(ExtractionJob(contract_id=contract.id, status=ExtractionJobStatus.QUEUED))
    await db_session.flush()

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.post("/api/v1/admin/extraction/retry", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["jobs_retried"] == 1
    assert body["jobs_succeeded"] == 0
    assert body["jobs_still_queued"] == 1


@pytest.mark.asyncio
async def test_audit_log_requires_admin_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, _admin = await _make_org_and_admin(db_session, org_name="Acme", email="audit1@example.com")
    viewer = User(
        org_id=org.id,
        email="viewer-audit@example.com",
        hashed_password="irrelevant",
        role=UserRole.VIEWER,
        full_name="A Viewer",
    )
    db_session.add(viewer)
    await db_session.flush()

    token = create_access_token(user_id=viewer.id, org_id=org.id, role=UserRole.VIEWER)
    response = await client.get("/api/v1/audit-log", headers=_auth_headers(token))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_is_scoped_to_org(client: AsyncClient, db_session: AsyncSession) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="auditA@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="auditB@example.com"
    )
    db_session.add(
        AuditLog(
            org_id=org_a.id,
            user_id=admin_a.id,
            action="user.login",
            entity_type="user",
            entity_id=admin_a.id,
            metadata_={"note": "org a event"},
        )
    )
    db_session.add(
        AuditLog(
            org_id=org_b.id,
            user_id=admin_b.id,
            action="user.login",
            entity_type="user",
            entity_id=admin_b.id,
        )
    )
    await db_session.flush()

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.get("/api/v1/audit-log", headers=_auth_headers(token_a))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["metadata"] == {"note": "org a event"}


@pytest.mark.asyncio
async def test_audit_log_filters_by_entity_type(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="audit2@example.com")
    db_session.add(
        AuditLog(org_id=org.id, user_id=admin.id, action="user.login", entity_type="user")
    )
    db_session.add(
        AuditLog(
            org_id=org.id,
            user_id=admin.id,
            action="obligation.edit",
            entity_type="obligation",
            entity_id=uuid.uuid4(),
        )
    )
    await db_session.flush()

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.get(
        "/api/v1/audit-log", params={"entity_type": "obligation"}, headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["entity_type"] == "obligation"
