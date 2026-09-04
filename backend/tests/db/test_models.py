from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    AlertType,
    ContractStatus,
    ContractType,
    LLMProviderName,
    ObligationCategory,
    ObligationStatus,
    RecurrenceType,
    UserRole,
)
from app.db.models import Alert, Contract, LLMUsageLog, Obligation, Organization, User


async def _make_org_and_user(session: AsyncSession, *, email: str = "counsel@acme.test") -> User:
    org = Organization(name="Acme Corp")
    session.add(org)
    await session.flush()

    user = User(
        org_id=org.id,
        email=email,
        hashed_password="not-a-real-hash",
        role=UserRole.LEGAL_OPS,
        full_name="Jamie Counsel",
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_create_organization_and_user_relationship(db_session: AsyncSession) -> None:
    user = await _make_org_and_user(db_session)

    fetched_org = await db_session.get(Organization, user.org_id)
    assert fetched_org is not None
    await db_session.refresh(fetched_org, attribute_names=["users"])
    assert [u.id for u in fetched_org.users] == [user.id]


@pytest.mark.asyncio
async def test_users_email_unique_constraint(db_session: AsyncSession) -> None:
    org = Organization(name="Acme Corp")
    db_session.add(org)
    await db_session.flush()

    db_session.add(
        User(
            org_id=org.id,
            email="dup@acme.test",
            hashed_password="x",
            role=UserRole.VIEWER,
            full_name="First User",
        )
    )
    await db_session.flush()

    db_session.add(
        User(
            org_id=org.id,
            email="dup@acme.test",
            hashed_password="x",
            role=UserRole.VIEWER,
            full_name="Second User",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_contract_obligation_cascade_delete(db_session: AsyncSession) -> None:
    user = await _make_org_and_user(db_session, email="ops@acme.test")

    contract = Contract(
        org_id=user.org_id,
        uploaded_by=user.id,
        title="Master Services Agreement",
        contract_type=ContractType.MSA,
        original_filename="msa.pdf",
        storage_path="/storage/msa.pdf",
        file_hash="a" * 64,
        status=ContractStatus.NEEDS_REVIEW,
    )
    db_session.add(contract)
    await db_session.flush()

    obligation = Obligation(
        contract_id=contract.id,
        category=ObligationCategory.RENEWAL,
        description="Auto-renews unless terminated with 60 days notice.",
        trigger_date=date(2027, 1, 1),
        notice_period_days=60,
        recurrence=RecurrenceType.ANNUALLY,
        status=ObligationStatus.UPCOMING,
    )
    db_session.add(obligation)
    await db_session.flush()

    alert = Alert(
        obligation_id=obligation.id,
        alert_type=AlertType.EMAIL,
        scheduled_for=datetime(2026, 11, 1, tzinfo=UTC),
        recipient_user_id=user.id,
    )
    db_session.add(alert)
    await db_session.flush()

    await db_session.delete(contract)
    await db_session.flush()

    assert await db_session.get(Obligation, obligation.id) is None
    assert await db_session.get(Alert, alert.id) is None


@pytest.mark.asyncio
async def test_llm_usage_log_unique_provider_date(db_session: AsyncSession) -> None:
    today = date(2026, 9, 4)
    db_session.add(LLMUsageLog(provider=LLMProviderName.GROQ, date=today))
    await db_session.flush()

    db_session.add(LLMUsageLog(provider=LLMProviderName.GROQ, date=today))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_obligation_category_enum_round_trips_as_value_not_name(
    db_session: AsyncSession,
) -> None:
    """Regression test for the pg_enum() `values_callable` wiring: without
    it, SQLAlchemy persists the Python member *name* (e.g. "RENEWAL") rather
    than `.value`, which for members like TERMINATION_NOTICE happens to
    match anyway but would silently diverge for e.g. UserRole.ADMIN
    ("ADMIN" vs "admin")."""
    user = await _make_org_and_user(db_session, email="review@acme.test")
    assert user.role == UserRole.LEGAL_OPS

    contract = Contract(
        org_id=user.org_id,
        uploaded_by=user.id,
        title="NDA",
        contract_type=ContractType.NDA,
        original_filename="nda.pdf",
        storage_path="/storage/nda.pdf",
        file_hash="b" * 64,
        status=ContractStatus.ACTIVE,
    )
    db_session.add(contract)
    await db_session.flush()

    db_session.add(
        Obligation(
            contract_id=contract.id,
            category=ObligationCategory.CONFIDENTIALITY,
            description="Both parties keep terms confidential.",
            recurrence=RecurrenceType.NONE,
            status=ObligationStatus.RESOLVED,
        )
    )
    await db_session.flush()

    stored_role = (
        await db_session.execute(select(User.role).where(User.id == user.id))
    ).scalar_one()
    assert stored_role == UserRole.LEGAL_OPS

    stored_category = (
        await db_session.execute(
            select(Obligation.category).where(Obligation.contract_id == contract.id)
        )
    ).scalar_one()
    assert stored_category == ObligationCategory.CONFIDENTIALITY
