from datetime import date, timedelta

from app.db.enums import ObligationStatus
from app.services.obligation_dates import compute_alert_date, initial_obligation_status


def test_compute_alert_date_subtracts_notice_period() -> None:
    assert compute_alert_date(date(2027, 1, 1), 30) == date(2026, 12, 2)


def test_compute_alert_date_is_none_without_trigger_date() -> None:
    assert compute_alert_date(None, 30) is None


def test_compute_alert_date_is_none_without_notice_period() -> None:
    assert compute_alert_date(date(2027, 1, 1), None) is None


def test_status_is_upcoming_without_trigger_date() -> None:
    assert initial_obligation_status(None, None) == ObligationStatus.UPCOMING


def test_status_is_overdue_when_trigger_date_in_past() -> None:
    yesterday = date.today() - timedelta(days=1)
    assert initial_obligation_status(yesterday, None) == ObligationStatus.OVERDUE


def test_status_is_at_risk_when_alert_date_has_arrived() -> None:
    trigger = date.today() + timedelta(days=10)
    alert = date.today() - timedelta(days=1)
    assert initial_obligation_status(trigger, alert) == ObligationStatus.AT_RISK


def test_status_is_upcoming_when_alert_date_is_in_the_future() -> None:
    trigger = date.today() + timedelta(days=60)
    alert = date.today() + timedelta(days=30)
    assert initial_obligation_status(trigger, alert) == ObligationStatus.UPCOMING
