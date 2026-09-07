import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.enums import ContractStatus, ObligationCategory, ObligationStatus, UserRole
from app.db.models import Contract, Obligation, Organization, User


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
    db_session: AsyncSession,
    *,
    org_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    status: ContractStatus = ContractStatus.PROCESSING,
    contract_value: float | None = None,
    currency: str | None = None,
) -> Contract:
    contract = Contract(
        org_id=org_id,
        uploaded_by=uploaded_by,
        title="Vendor Agreement",
        original_filename="vendor.pdf",
        storage_path="storage/vendor.pdf",
        file_hash=uuid.uuid4().hex + "a" * 24,
        status=status,
        contract_value=contract_value,
        currency=currency,
    )
    db_session.add(contract)
    await db_session.flush()
    return contract


async def _make_obligation(
    db_session: AsyncSession,
    *,
    contract_id: uuid.UUID,
    status: ObligationStatus,
    trigger_date: date | None = None,
) -> Obligation:
    obligation = Obligation(
        contract_id=contract_id,
        category=ObligationCategory.PAYMENT_MILESTONE,
        description="Pay the annual license fee.",
        responsible_party="Us",
        trigger_date=trigger_date,
        status=status,
        confidence_score=0.5,
    )
    db_session.add(obligation)
    await db_session.flush()
    return obligation


@pytest.mark.asyncio
async def test_dashboard_summary_counts_and_active_value(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(db_session, org_name="Acme", email="dash1@example.com")
    contract = await _make_contract(
        db_session,
        org_id=org.id,
        uploaded_by=admin.id,
        status=ContractStatus.ACTIVE,
        contract_value=1000,
        currency="USD",
    )
    other_active = await _make_contract(
        db_session,
        org_id=org.id,
        uploaded_by=admin.id,
        status=ContractStatus.ACTIVE,
        contract_value=500,
        currency="USD",
    )
    await _make_contract(
        db_session,
        org_id=org.id,
        uploaded_by=admin.id,
        status=ContractStatus.PROCESSING,
        contract_value=9999,
        currency="USD",
    )

    await _make_obligation(db_session, contract_id=contract.id, status=ObligationStatus.AT_RISK)
    await _make_obligation(db_session, contract_id=contract.id, status=ObligationStatus.OVERDUE)
    await _make_obligation(db_session, contract_id=contract.id, status=ObligationStatus.OVERDUE)
    await _make_obligation(
        db_session,
        contract_id=other_active.id,
        status=ObligationStatus.UPCOMING,
        trigger_date=date.today() + timedelta(days=1),
    )
    # Upcoming, but next month — must not be counted this month.
    far_future = date.today().replace(day=28) + timedelta(days=40)
    await _make_obligation(
        db_session,
        contract_id=contract.id,
        status=ObligationStatus.UPCOMING,
        trigger_date=far_future,
    )

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.get("/api/v1/dashboard/summary", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["at_risk_count"] == 1
    assert body["overdue_count"] == 2
    assert body["upcoming_this_month_count"] == 1
    assert body["total_active_contract_value"] == {"USD": 1500.0}


@pytest.mark.asyncio
async def test_dashboard_summary_is_scoped_to_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="dashA@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="dashB@example.com"
    )
    contract_b = await _make_contract(
        db_session,
        org_id=org_b.id,
        uploaded_by=admin_b.id,
        status=ContractStatus.ACTIVE,
        contract_value=100000,
        currency="USD",
    )
    await _make_obligation(db_session, contract_id=contract_b.id, status=ObligationStatus.OVERDUE)

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.get("/api/v1/dashboard/summary", headers=_auth_headers(token_a))

    assert response.status_code == 200
    body = response.json()
    assert body["overdue_count"] == 0
    assert body["total_active_contract_value"] == {}
