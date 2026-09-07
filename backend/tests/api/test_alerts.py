import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.enums import (
    AlertStatus,
    AlertType,
    ContractStatus,
    ObligationCategory,
    ObligationStatus,
    UserRole,
)
from app.db.models import Alert, Contract, Obligation, Organization, User
from app.services import alerts as alerts_module

from .test_obligations import _make_obligation


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


async def _make_contract(
    db_session: AsyncSession, *, org_id: uuid.UUID, uploaded_by: uuid.UUID
) -> Contract:
    contract = Contract(
        org_id=org_id,
        uploaded_by=uploaded_by,
        title="Vendor Agreement",
        original_filename="vendor.pdf",
        storage_path="storage/vendor.pdf",
        file_hash=uuid.uuid4().hex + "a" * 24,
        status=ContractStatus.ACTIVE,
    )
    db_session.add(contract)
    await db_session.flush()
    return contract


async def _make_alert(
    db_session: AsyncSession, *, obligation_id: uuid.UUID, recipient_user_id: uuid.UUID
) -> Alert:
    alert = Alert(
        obligation_id=obligation_id,
        alert_type=AlertType.EMAIL,
        scheduled_for=datetime.now(UTC),
        recipient_user_id=recipient_user_id,
        status=AlertStatus.SENT,
    )
    db_session.add(alert)
    await db_session.flush()
    return alert


@pytest.mark.asyncio
async def test_list_alerts_is_scoped_to_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="al-a@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="al-b@example.com"
    )
    contract_a = await _make_contract(db_session, org_id=org_a.id, uploaded_by=admin_a.id)
    contract_b = await _make_contract(db_session, org_id=org_b.id, uploaded_by=admin_b.id)
    obligation_a = await _make_obligation(db_session, contract_id=contract_a.id)
    obligation_b = await _make_obligation(db_session, contract_id=contract_b.id)
    await _make_alert(db_session, obligation_id=obligation_a.id, recipient_user_id=admin_a.id)
    await _make_alert(db_session, obligation_id=obligation_b.id, recipient_user_id=admin_b.id)

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.get("/api/v1/alerts", headers=_auth_headers(token_a))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["recipient_user_id"] == str(admin_a.id)


@pytest.mark.asyncio
async def test_dismiss_alert_by_recipient(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="dismiss1@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)
    alert = await _make_alert(db_session, obligation_id=obligation.id, recipient_user_id=admin.id)

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.patch(
        f"/api/v1/alerts/{alert.id}/dismiss", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_dismiss_alert_forbidden_for_unrelated_viewer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="dismiss2@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)
    alert = await _make_alert(db_session, obligation_id=obligation.id, recipient_user_id=admin.id)

    viewer = User(
        org_id=org.id,
        email="viewer-alerts@example.com",
        hashed_password="irrelevant",
        role=UserRole.VIEWER,
        full_name="A Viewer",
    )
    db_session.add(viewer)
    await db_session.flush()

    viewer_token = create_access_token(user_id=viewer.id, org_id=org.id, role=UserRole.VIEWER)
    response = await client.patch(
        f"/api/v1/alerts/{alert.id}/dismiss", headers=_auth_headers(viewer_token)
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_dismiss_alert_from_other_org_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="al-c@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="al-d@example.com"
    )
    contract_b = await _make_contract(db_session, org_id=org_b.id, uploaded_by=admin_b.id)
    obligation_b = await _make_obligation(db_session, contract_id=contract_b.id)
    alert_b = await _make_alert(
        db_session, obligation_id=obligation_b.id, recipient_user_id=admin_b.id
    )

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.patch(
        f"/api/v1/alerts/{alert_b.id}/dismiss", headers=_auth_headers(token_a)
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_trigger_alert_scan_requires_admin_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="scan1@example.com")
    legal_ops = User(
        org_id=org.id,
        email="legalops1@example.com",
        hashed_password="irrelevant",
        role=UserRole.LEGAL_OPS,
        full_name="Legal Ops",
    )
    db_session.add(legal_ops)
    await db_session.flush()

    token = create_access_token(user_id=legal_ops.id, org_id=org.id, role=UserRole.LEGAL_OPS)
    response = await client.post("/api/v1/admin/alerts/scan", headers=_auth_headers(token))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_trigger_alert_scan_returns_counts(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="scan2@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)

    obligation = Obligation(
        contract_id=contract.id,
        category=ObligationCategory.PAYMENT_MILESTONE,
        description="Pay the annual license fee.",
        responsible_party="Us",
        trigger_date=date.today() - timedelta(days=1),
        status=ObligationStatus.OVERDUE,
        confidence_score=0.5,
    )
    db_session.add(obligation)
    await db_session.flush()

    async def _fake_send(*, recipient_email: str, obligation: object) -> None:
        return None

    monkeypatch.setattr(alerts_module, "send_alert_email", _fake_send)

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.post("/api/v1/admin/alerts/scan", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["alerts_sent"] == 1
