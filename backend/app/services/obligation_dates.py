"""Obligation calendar math — deliberately plain Python, never delegated to
the LLM (docs/CONTRACT_CLM_BUILD_PLAN.md §3 point 5). Shared between the
Phase 5 extraction pipeline and the Phase 6 obligation-review API, so a
human editing `trigger_date`/`notice_period_days` gets the exact same
`computed_alert_date`/`status` recalculation the LLM path uses.
"""

from datetime import date, timedelta

from app.db.enums import ObligationStatus


def compute_alert_date(trigger_date: date | None, notice_period_days: int | None) -> date | None:
    if trigger_date is None or notice_period_days is None:
        return None
    return trigger_date - timedelta(days=notice_period_days)


def initial_obligation_status(
    trigger_date: date | None, computed_alert_date: date | None
) -> ObligationStatus:
    if trigger_date is None:
        return ObligationStatus.UPCOMING
    today = date.today()
    if trigger_date < today:
        return ObligationStatus.OVERDUE
    if computed_alert_date is not None and computed_alert_date <= today:
        return ObligationStatus.AT_RISK
    return ObligationStatus.UPCOMING
