import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.enums import (
    ContractStatus,
    ObligationCategory,
    ObligationStatus,
    RecurrenceType,
    UserRole,
)
from app.db.models import AuditLog, Contract, Obligation, Organization, User


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
        status=ContractStatus.PROCESSING,
    )
    db_session.add(contract)
    await db_session.flush()
    return contract


async def _make_obligation(
    db_session: AsyncSession,
    *,
    contract_id: uuid.UUID,
    category: ObligationCategory = ObligationCategory.PAYMENT_MILESTONE,
    status: ObligationStatus = ObligationStatus.UPCOMING,
    trigger_date: date | None = None,
    is_human_reviewed: bool = False,
) -> Obligation:
    obligation = Obligation(
        contract_id=contract_id,
        category=category,
        description="Pay the annual license fee.",
        responsible_party="Us",
        trigger_date=trigger_date,
        status=status,
        recurrence=RecurrenceType.ANNUALLY,
        confidence_score=0.5,
        is_human_reviewed=is_human_reviewed,
    )
    db_session.add(obligation)
    await db_session.flush()
    return obligation


@pytest.mark.asyncio
async def test_list_obligations_is_scoped_to_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(db_session, org_name="Org A", email="a1@example.com")
    org_b, admin_b = await _make_org_and_admin(db_session, org_name="Org B", email="b1@example.com")
    contract_a = await _make_contract(db_session, org_id=org_a.id, uploaded_by=admin_a.id)
    contract_b = await _make_contract(db_session, org_id=org_b.id, uploaded_by=admin_b.id)
    await _make_obligation(db_session, contract_id=contract_a.id)
    await _make_obligation(db_session, contract_id=contract_b.id)

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.get("/api/v1/obligations", headers=_auth_headers(token_a))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["contract_id"] == str(contract_a.id)


@pytest.mark.asyncio
async def test_list_obligations_filters_by_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="filt@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    await _make_obligation(db_session, contract_id=contract.id, status=ObligationStatus.OVERDUE)
    await _make_obligation(db_session, contract_id=contract.id, status=ObligationStatus.UPCOMING)

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.get(
        "/api/v1/obligations", params={"status": "overdue"}, headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "overdue"


@pytest.mark.asyncio
async def test_get_obligation_from_other_org_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(db_session, org_name="Org A", email="a2@example.com")
    org_b, admin_b = await _make_org_and_admin(db_session, org_name="Org B", email="b2@example.com")
    contract_b = await _make_contract(db_session, org_id=org_b.id, uploaded_by=admin_b.id)
    obligation_b = await _make_obligation(db_session, contract_id=contract_b.id)

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.get(
        f"/api/v1/obligations/{obligation_b.id}", headers=_auth_headers(token_a)
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_obligation_requires_editor_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="viewer-org@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)

    viewer = User(
        org_id=org.id,
        email="viewer3@example.com",
        hashed_password="irrelevant",
        role=UserRole.VIEWER,
        full_name="A Viewer",
    )
    db_session.add(viewer)
    await db_session.flush()

    viewer_token = create_access_token(user_id=viewer.id, org_id=org.id, role=UserRole.VIEWER)
    response = await client.patch(
        f"/api/v1/obligations/{obligation.id}",
        json={"description": "Edited"},
        headers=_auth_headers(viewer_token),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_patch_obligation_empty_body_confirms_review(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="confirm@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(
        db_session, contract_id=contract.id, is_human_reviewed=False
    )

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.patch(
        f"/api/v1/obligations/{obligation.id}", json={}, headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_human_reviewed"] is True
    assert body["description"] == "Pay the annual license fee."


@pytest.mark.asyncio
async def test_patch_obligation_waive_sets_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="waive@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.patch(
        f"/api/v1/obligations/{obligation.id}",
        json={"status": "waived"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "waived"


@pytest.mark.asyncio
async def test_patch_obligation_rejects_assignee_from_another_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="assign-owner@example.com"
    )
    other_org, other_user = await _make_org_and_admin(
        db_session, org_name="Other Org", email="assign-outsider@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.patch(
        f"/api/v1/obligations/{obligation.id}",
        json={"assigned_to": str(other_user.id)},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert obligation.assigned_to is None


@pytest.mark.asyncio
async def test_patch_obligation_accepts_assignee_from_same_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="assign-owner2@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)

    legal_ops = User(
        org_id=org.id,
        email="assign-teammate@example.com",
        hashed_password="irrelevant",
        role=UserRole.LEGAL_OPS,
        full_name="Teammate",
    )
    db_session.add(legal_ops)
    await db_session.flush()

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.patch(
        f"/api/v1/obligations/{obligation.id}",
        json={"assigned_to": str(legal_ops.id)},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == str(legal_ops.id)


@pytest.mark.asyncio
async def test_patch_obligation_edits_trigger_date_recomputes_alert_and_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="recompute@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.patch(
        f"/api/v1/obligations/{obligation.id}",
        json={"trigger_date": yesterday},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trigger_date"] == yesterday
    assert body["status"] == "overdue"


@pytest.mark.asyncio
async def test_calendar_excludes_far_future_and_closed_obligations(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="calendar@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)

    soon = await _make_obligation(
        db_session,
        contract_id=contract.id,
        trigger_date=date.today() + timedelta(days=10),
        status=ObligationStatus.UPCOMING,
    )
    await _make_obligation(
        db_session,
        contract_id=contract.id,
        trigger_date=date.today() + timedelta(days=300),
        status=ObligationStatus.UPCOMING,
    )
    await _make_obligation(
        db_session,
        contract_id=contract.id,
        trigger_date=date.today() + timedelta(days=5),
        status=ObligationStatus.WAIVED,
    )

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.get(
        "/api/v1/obligations/calendar", params={"within_days": 90}, headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(soon.id)


@pytest.mark.asyncio
async def test_create_obligation_requires_editor_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="create-viewer-org@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    viewer = User(
        org_id=org.id,
        email="viewer-create@example.com",
        hashed_password="irrelevant",
        role=UserRole.VIEWER,
        full_name="A Viewer",
    )
    db_session.add(viewer)
    await db_session.flush()

    viewer_token = create_access_token(user_id=viewer.id, org_id=org.id, role=UserRole.VIEWER)
    payload = {
        "contract_id": str(contract.id),
        "category": ObligationCategory.PAYMENT_MILESTONE.value,
        "description": "Annual license fee.",
    }
    response = await client.post(
        "/api/v1/obligations",
        json=payload,
        headers=_auth_headers(viewer_token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_obligation_success(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="create-success@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    trigger_date = date.today() + timedelta(days=30)
    notice_days = 10

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    payload = {
        "contract_id": str(contract.id),
        "category": ObligationCategory.PAYMENT_MILESTONE.value,
        "description": "Annual software license renewal",
        "responsible_party": "Customer",
        "trigger_date": trigger_date.isoformat(),
        "notice_period_days": notice_days,
        "monetary_amount": 15000.0,
        "currency": "USD",
        "recurrence": RecurrenceType.ANNUALLY.value,
        "assigned_to": str(admin.id),
    }
    response = await client.post(
        "/api/v1/obligations",
        json=payload,
        headers=_auth_headers(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["contract_id"] == str(contract.id)
    assert body["contract_title"] == "Vendor Agreement"
    assert body["category"] == ObligationCategory.PAYMENT_MILESTONE.value
    assert body["description"] == "Annual software license renewal"
    assert body["responsible_party"] == "Customer"
    assert body["trigger_date"] == trigger_date.isoformat()
    assert body["notice_period_days"] == notice_days
    assert body["computed_alert_date"] == (trigger_date - timedelta(days=notice_days)).isoformat()
    assert body["monetary_amount"] == 15000.0
    assert body["currency"] == "USD"
    assert body["recurrence"] == RecurrenceType.ANNUALLY.value
    assert body["assigned_to"] == str(admin.id)
    assert body["confidence_score"] == 1.0
    assert body["is_human_reviewed"] is True
    assert body["status"] == "upcoming"

    created_id = uuid.UUID(body["id"])
    audit_res = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == created_id,
            AuditLog.action == "obligation.create",
        )
    )
    audit = audit_res.scalar_one_or_none()
    assert audit is not None
    assert audit.org_id == org.id
    assert audit.user_id == admin.id


@pytest.mark.asyncio
async def test_create_obligation_rejects_other_org_contract(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="org-a-create@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="org-b-create@example.com"
    )
    contract_b = await _make_contract(db_session, org_id=org_b.id, uploaded_by=admin_b.id)

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    payload = {
        "contract_id": str(contract_b.id),
        "category": ObligationCategory.AUDIT_RIGHTS.value,
        "description": "Cross-org contract obligation attempt",
    }
    response = await client.post(
        "/api/v1/obligations",
        json=payload,
        headers=_auth_headers(token_a),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_obligation_rejects_other_org_assignee(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="org-a-assign@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="org-b-assign@example.com"
    )
    contract_a = await _make_contract(db_session, org_id=org_a.id, uploaded_by=admin_a.id)

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    payload = {
        "contract_id": str(contract_a.id),
        "category": ObligationCategory.AUDIT_RIGHTS.value,
        "description": "Cross-org assignee attempt",
        "assigned_to": str(admin_b.id),
    }
    response = await client.post(
        "/api/v1/obligations",
        json=payload,
        headers=_auth_headers(token_a),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_delete_obligation_requires_editor_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="delete-viewer-org@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)

    viewer = User(
        org_id=org.id,
        email="viewer-del@example.com",
        hashed_password="irrelevant",
        role=UserRole.VIEWER,
        full_name="A Viewer",
    )
    db_session.add(viewer)
    await db_session.flush()

    viewer_token = create_access_token(user_id=viewer.id, org_id=org.id, role=UserRole.VIEWER)
    response = await client.delete(
        f"/api/v1/obligations/{obligation.id}",
        headers=_auth_headers(viewer_token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_obligation_success(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="del-success@example.com"
    )
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(db_session, contract_id=contract.id)

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.delete(
        f"/api/v1/obligations/{obligation.id}",
        headers=_auth_headers(token),
    )
    assert response.status_code == 204

    deleted = await db_session.get(Obligation, obligation.id)
    assert deleted is None

    audit_res = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == obligation.id,
            AuditLog.action == "obligation.delete",
        )
    )
    audit = audit_res.scalar_one_or_none()
    assert audit is not None
    assert audit.org_id == org.id
    assert audit.user_id == admin.id


@pytest.mark.asyncio
async def test_delete_obligation_from_other_org_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="del-a@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="del-b@example.com"
    )
    contract_b = await _make_contract(db_session, org_id=org_b.id, uploaded_by=admin_b.id)
    obligation_b = await _make_obligation(db_session, contract_id=contract_b.id)

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.delete(
        f"/api/v1/obligations/{obligation_b.id}",
        headers=_auth_headers(token_a),
    )
    assert response.status_code == 404

    remaining = await db_session.get(Obligation, obligation_b.id)
    assert remaining is not None

