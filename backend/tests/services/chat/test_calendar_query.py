from datetime import date

from app.db.enums import ObligationCategory, ObligationStatus
from app.services.chat.calendar_query import parse_calendar_query

_TODAY = date(2026, 9, 7)  # a Monday, well inside Q3


def test_overdue_status_forces_backward_looking_range() -> None:
    result = parse_calendar_query("show me overdue obligations", today=_TODAY)

    assert result.status == ObligationStatus.OVERDUE
    assert result.trigger_date_from is None
    assert result.trigger_date_to == _TODAY


def test_at_risk_status_keyword() -> None:
    result = parse_calendar_query("what's at risk right now?", today=_TODAY)

    assert result.status == ObligationStatus.AT_RISK


def test_category_keyword_matches_before_shorter_substring() -> None:
    result = parse_calendar_query(
        "any termination notice obligations coming up?", today=_TODAY
    )

    assert result.category == ObligationCategory.TERMINATION_NOTICE


def test_renewal_category_keyword() -> None:
    result = parse_calendar_query("which renewals are due?", today=_TODAY)

    assert result.category == ObligationCategory.RENEWAL


def test_next_n_days_pattern() -> None:
    result = parse_calendar_query("what's due in the next 45 days?", today=_TODAY)

    assert result.trigger_date_from == _TODAY
    assert result.trigger_date_to == date(2026, 10, 22)


def test_within_n_days_pattern() -> None:
    result = parse_calendar_query("anything within 10 days?", today=_TODAY)

    assert result.trigger_date_from == _TODAY
    assert result.trigger_date_to == date(2026, 9, 17)


def test_this_week() -> None:
    result = parse_calendar_query("what's due this week?", today=_TODAY)

    assert result.trigger_date_from == _TODAY
    assert result.trigger_date_to == date(2026, 9, 14)


def test_this_month_bounds() -> None:
    result = parse_calendar_query("obligations due this month", today=_TODAY)

    assert result.trigger_date_from == date(2026, 9, 1)
    assert result.trigger_date_to == date(2026, 9, 30)


def test_next_month_bounds() -> None:
    result = parse_calendar_query("what's coming up next month?", today=_TODAY)

    assert result.trigger_date_from == date(2026, 10, 1)
    assert result.trigger_date_to == date(2026, 10, 31)


def test_next_month_rolls_over_into_next_year() -> None:
    result = parse_calendar_query("next month's obligations", today=date(2026, 12, 15))

    assert result.trigger_date_from == date(2027, 1, 1)
    assert result.trigger_date_to == date(2027, 1, 31)


def test_this_quarter_bounds() -> None:
    result = parse_calendar_query("what's due this quarter?", today=_TODAY)

    assert result.trigger_date_from == date(2026, 7, 1)
    assert result.trigger_date_to == date(2026, 9, 30)


def test_next_quarter_bounds() -> None:
    result = parse_calendar_query("renewals next quarter", today=_TODAY)

    assert result.trigger_date_from == date(2026, 10, 1)
    assert result.trigger_date_to == date(2026, 12, 31)


def test_next_quarter_rolls_over_into_next_year() -> None:
    result = parse_calendar_query("next quarter's renewals", today=date(2026, 11, 20))

    assert result.trigger_date_from == date(2027, 1, 1)
    assert result.trigger_date_to == date(2027, 3, 31)


def test_this_year_bounds() -> None:
    result = parse_calendar_query("everything due this year", today=_TODAY)

    assert result.trigger_date_from == date(2026, 1, 1)
    assert result.trigger_date_to == date(2026, 12, 31)


def test_no_recognized_phrase_leaves_filters_unset() -> None:
    result = parse_calendar_query("obligations", today=_TODAY)

    assert result.status is None
    assert result.category is None
    assert result.trigger_date_from is None
    assert result.trigger_date_to is None


def test_status_and_category_combine() -> None:
    result = parse_calendar_query("overdue payment obligations", today=_TODAY)

    assert result.status == ObligationStatus.OVERDUE
    assert result.category == ObligationCategory.PAYMENT_MILESTONE
