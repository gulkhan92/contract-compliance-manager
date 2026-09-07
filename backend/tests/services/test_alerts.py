import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    AlertStatus,
    ContractStatus,
    ObligationCategory,
    ObligationStatus,
    UserRole,
)
from app.db.models import Alert, Contract, Obligation, Organization, User
from app.services import alerts as alerts_module
from app.services.alerts import run_alert_scan
from app.services.email import EmailSendError


async def _make_org_and_user(db_session: AsyncSession, *, email: str) -> tuple[Organization, User]:
    org = Organization(name="Alerts Test Org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=email,
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        full_name="Org Admin",
    )
    db_session.add(user)
    await db_session.flush()
    return org, user


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


async def _make_obligation(
    db_session: AsyncSession,
    *,
    contract_id: uuid.UUID,
    status: ObligationStatus,
    trigger_date: date | None,
    computed_alert_date: date | None = None,
    assigned_to: uuid.UUID | None = None,
) -> Obligation:
    obligation = Obligation(
        contract_id=contract_id,
        category=ObligationCategory.PAYMENT_MILESTONE,
        description="Pay the annual license fee.",
        responsible_party="Us",
        trigger_date=trigger_date,
        computed_alert_date=computed_alert_date,
        status=status,
        confidence_score=0.5,
        assigned_to=assigned_to,
    )
    db_session.add(obligation)
    await db_session.flush()
    return obligation


@pytest.mark.asyncio
async def test_recompute_transitions_upcoming_to_overdue(db_session: AsyncSession) -> None:
    org, admin = await _make_org_and_user(db_session, email="recompute1@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    yesterday = date.today() - timedelta(days=1)
    obligation = await _make_obligation(
        db_session,
        contract_id=contract.id,
        status=ObligationStatus.UPCOMING,
        trigger_date=yesterday,
    )

    result = await run_alert_scan(db_session)

    assert result.statuses_recomputed == 1
    await db_session.refresh(obligation)
    assert obligation.status == ObligationStatus.OVERDUE


@pytest.mark.asyncio
async def test_scan_sends_alert_for_overdue_obligation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, admin = await _make_org_and_user(db_session, email="send1@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    obligation = await _make_obligation(
        db_session,
        contract_id=contract.id,
        status=ObligationStatus.OVERDUE,
        trigger_date=date.today() - timedelta(days=1),
    )

    sent_to: list[str] = []

    async def _fake_send(*, recipient_email: str, obligation: Obligation) -> None:
        sent_to.append(recipient_email)

    monkeypatch.setattr(alerts_module, "send_alert_email", _fake_send)

    result = await run_alert_scan(db_session)

    assert result.alerts_sent == 1
    assert sent_to == [admin.email]

    alert_result = await db_session.execute(Alert.__table__.select())
    rows = alert_result.fetchall()
    assert len(rows) == 1
    assert rows[0].status == AlertStatus.SENT
    assert rows[0].obligation_id == obligation.id


@pytest.mark.asyncio
async def test_scan_marks_alert_failed_on_smtp_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, admin = await _make_org_and_user(db_session, email="fail1@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    await _make_obligation(
        db_session,
        contract_id=contract.id,
        status=ObligationStatus.AT_RISK,
        trigger_date=date.today() + timedelta(days=10),
        computed_alert_date=date.today() - timedelta(days=1),
    )

    async def _fake_send(*, recipient_email: str, obligation: Obligation) -> None:
        raise EmailSendError("SMTP is down")

    monkeypatch.setattr(alerts_module, "send_alert_email", _fake_send)

    result = await run_alert_scan(db_session)

    assert result.alerts_sent == 0
    assert result.alerts_failed == 1

    alert_result = await db_session.execute(Alert.__table__.select())
    rows = alert_result.fetchall()
    assert rows[0].status == AlertStatus.FAILED
    assert rows[0].sent_at is None


@pytest.mark.asyncio
async def test_scan_does_not_resend_same_day(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, admin = await _make_org_and_user(db_session, email="dup1@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    await _make_obligation(
        db_session,
        contract_id=contract.id,
        status=ObligationStatus.OVERDUE,
        trigger_date=date.today() - timedelta(days=1),
    )

    call_count = 0

    async def _fake_send(*, recipient_email: str, obligation: Obligation) -> None:
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr(alerts_module, "send_alert_email", _fake_send)

    first = await run_alert_scan(db_session)
    second = await run_alert_scan(db_session)

    assert first.alerts_sent == 1
    assert second.alerts_sent == 0
    assert second.alerts_skipped_duplicate == 1
    assert call_count == 1


@pytest.mark.asyncio
async def test_scan_prefers_assignee_over_uploader(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, admin = await _make_org_and_user(db_session, email="uploader@example.com")
    assignee = User(
        org_id=org.id,
        email="assignee@example.com",
        hashed_password="irrelevant",
        role=UserRole.LEGAL_OPS,
        full_name="Assignee",
    )
    db_session.add(assignee)
    await db_session.flush()

    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=admin.id)
    await _make_obligation(
        db_session,
        contract_id=contract.id,
        status=ObligationStatus.OVERDUE,
        trigger_date=date.today() - timedelta(days=1),
        assigned_to=assignee.id,
    )

    sent_to: list[str] = []

    async def _fake_send(*, recipient_email: str, obligation: Obligation) -> None:
        sent_to.append(recipient_email)

    monkeypatch.setattr(alerts_module, "send_alert_email", _fake_send)

    await run_alert_scan(db_session)

    assert sent_to == [assignee.email]
