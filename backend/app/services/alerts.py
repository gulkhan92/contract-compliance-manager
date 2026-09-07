"""Daily compliance-calendar maintenance: recompute every open obligation's
status from today's date (upcoming/at-risk/overdue), then send one EMAIL
alert per obligation that's newly in an alertable state — at most once per
calendar day per obligation, per docs/CONTRACT_CLM_BUILD_PLAN.md §9/§12
Phase 7. Every obligation's send is isolated in its own try/except so one
SMTP failure never aborts the rest of the batch.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.enums import AlertStatus, AlertType, ObligationStatus
from app.db.models import Alert, Contract, Obligation, User
from app.services.email import EmailSendError, send_alert_email
from app.services.obligation_dates import initial_obligation_status

logger = logging.getLogger(__name__)

_ALERTABLE_STATUSES = (ObligationStatus.AT_RISK, ObligationStatus.OVERDUE)
_OPEN_STATUSES = (*_ALERTABLE_STATUSES, ObligationStatus.UPCOMING)


@dataclass
class AlertScanResult:
    statuses_recomputed: int = 0
    alerts_sent: int = 0
    alerts_failed: int = 0
    alerts_skipped_duplicate: int = 0


async def _recompute_statuses(session: AsyncSession) -> int:
    result = await session.execute(
        select(Obligation).where(
            Obligation.status.in_(_OPEN_STATUSES), Obligation.trigger_date.is_not(None)
        )
    )
    changed = 0
    for obligation in result.scalars().all():
        new_status = initial_obligation_status(
            obligation.trigger_date, obligation.computed_alert_date
        )
        if new_status != obligation.status:
            obligation.status = new_status
            changed += 1
    await session.flush()
    return changed


async def _already_alerted_today(
    session: AsyncSession, *, obligation: Obligation, recipient_user_id: uuid.UUID
) -> bool:
    # Deliberately UTC's "today", not the server's local date — scheduled_for
    # is always stored as datetime.now(UTC), so the boundary must match.
    today_start = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
    result = await session.execute(
        select(Alert.id).where(
            Alert.obligation_id == obligation.id,
            Alert.recipient_user_id == recipient_user_id,
            Alert.status.in_((AlertStatus.PENDING, AlertStatus.SENT)),
            Alert.scheduled_for >= today_start,
        )
    )
    return result.scalar_one_or_none() is not None


def _resolve_recipient(obligation: Obligation) -> User:
    """The obligation's assignee if one's been set during review, otherwise
    the contract's original uploader — Contract.uploaded_by is a required
    FK, so there's always exactly one of those to fall back to."""
    return obligation.assignee or obligation.contract.uploaded_by_user


async def run_alert_scan(session: AsyncSession) -> AlertScanResult:
    outcome = AlertScanResult()
    outcome.statuses_recomputed = await _recompute_statuses(session)

    result = await session.execute(
        select(Obligation)
        .where(Obligation.status.in_(_ALERTABLE_STATUSES))
        .options(
            selectinload(Obligation.assignee),
            selectinload(Obligation.contract).selectinload(Contract.uploaded_by_user),
        )
    )
    for obligation in result.scalars().all():
        recipient = _resolve_recipient(obligation)

        if await _already_alerted_today(
            session, obligation=obligation, recipient_user_id=recipient.id
        ):
            outcome.alerts_skipped_duplicate += 1
            continue

        alert = Alert(
            obligation_id=obligation.id,
            alert_type=AlertType.EMAIL,
            scheduled_for=datetime.now(UTC),
            recipient_user_id=recipient.id,
            status=AlertStatus.PENDING,
        )
        session.add(alert)
        await session.flush()

        try:
            await send_alert_email(recipient_email=recipient.email, obligation=obligation)
        except EmailSendError as exc:
            logger.warning("Alert email failed for obligation %s: %s", obligation.id, exc)
            alert.status = AlertStatus.FAILED
            outcome.alerts_failed += 1
        else:
            alert.status = AlertStatus.SENT
            alert.sent_at = datetime.now(UTC)
            outcome.alerts_sent += 1

    await session.flush()
    return outcome
