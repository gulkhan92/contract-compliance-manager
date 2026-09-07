"""NL-to-filter parsing for the calendar-query intent (plan §2 diagram,
§6.1's routing, and §12.2). Deliberately a constrained keyword/regex parser
producing a structured filter object applied through ordinary SQLAlchemy
predicates — never an LLM asked to emit raw SQL, which would be both a
real injection surface and unnecessary: calendar phrasing in practice is a
small, enumerable set of date-range and status/category words, not
open-ended natural language requiring a language model to parse.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.enums import ObligationCategory, ObligationStatus
from app.db.models import Contract, Obligation
from app.schemas.chat import ChatAnswer, ChatCitation

_MAX_RESULTS = 15

_STATUS_KEYWORDS: dict[str, ObligationStatus] = {
    "overdue": ObligationStatus.OVERDUE,
    "past due": ObligationStatus.OVERDUE,
    "at risk": ObligationStatus.AT_RISK,
    "at-risk": ObligationStatus.AT_RISK,
    "upcoming": ObligationStatus.UPCOMING,
    "resolved": ObligationStatus.RESOLVED,
    "completed": ObligationStatus.RESOLVED,
    "waived": ObligationStatus.WAIVED,
}

# Ordered so a more specific phrase (e.g. "termination notice") is checked
# before a shorter substring that could also appear inside it.
_CATEGORY_KEYWORDS: list[tuple[str, ObligationCategory]] = [
    ("termination notice", ObligationCategory.TERMINATION_NOTICE),
    ("renewal", ObligationCategory.RENEWAL),
    ("payment", ObligationCategory.PAYMENT_MILESTONE),
    ("invoice", ObligationCategory.PAYMENT_MILESTONE),
    ("sla", ObligationCategory.SLA_COMMITMENT),
    ("service level", ObligationCategory.SLA_COMMITMENT),
    ("indemnif", ObligationCategory.INDEMNIFICATION),
    ("confidential", ObligationCategory.CONFIDENTIALITY),
    ("non-compete", ObligationCategory.NON_COMPETE),
    ("noncompete", ObligationCategory.NON_COMPETE),
    ("liability", ObligationCategory.LIMITATION_OF_LIABILITY),
    ("governing law", ObligationCategory.GOVERNING_LAW),
    ("audit", ObligationCategory.AUDIT_RIGHTS),
    ("data protection", ObligationCategory.DATA_PROTECTION),
    ("gdpr", ObligationCategory.DATA_PROTECTION),
]

_NEXT_N_DAYS_PATTERN = re.compile(r"next\s+(\d+)\s*days?", re.I)
_WITHIN_N_DAYS_PATTERN = re.compile(r"within\s+(\d+)\s*days?", re.I)


@dataclass(frozen=True)
class CalendarQueryFilters:
    status: ObligationStatus | None = None
    category: ObligationCategory | None = None
    trigger_date_from: date | None = None
    trigger_date_to: date | None = None


def _quarter_start(quarter_index: int, base_year: int) -> date:
    """`quarter_index` counts quarters from Q1 of `base_year` (0 = Q1,
    1 = Q2, ... 4 = Q1 of the next year, -1 = Q4 of the previous year —
    Python's floor-division/modulo on a negative index handles the
    year-rollback direction correctly too)."""
    year = base_year + quarter_index // 4
    month = (quarter_index % 4) * 3 + 1
    return date(year, month, 1)


def _quarter_bounds(d: date, *, offset_quarters: int = 0) -> tuple[date, date]:
    quarter_index = (d.month - 1) // 3 + offset_quarters
    start = _quarter_start(quarter_index, d.year)
    end = _quarter_start(quarter_index + 1, d.year) - timedelta(days=1)
    return start, end


def _month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month - timedelta(days=1)


def parse_calendar_query(query_text: str, *, today: date | None = None) -> CalendarQueryFilters:
    today = today or date.today()
    lowered = query_text.lower()

    status = next((v for k, v in _STATUS_KEYWORDS.items() if k in lowered), None)
    category = next((v for k, v in _CATEGORY_KEYWORDS if k in lowered), None)

    date_from: date | None = None
    date_to: date | None = None

    # Two distinct patterns kept as separate branches (not combined via
    # `or`) so each stays independently readable/greppable.
    if match := _NEXT_N_DAYS_PATTERN.search(lowered):  # noqa: SIM114
        date_from, date_to = today, today + timedelta(days=int(match.group(1)))
    elif match := _WITHIN_N_DAYS_PATTERN.search(lowered):
        date_from, date_to = today, today + timedelta(days=int(match.group(1)))
    elif "this week" in lowered:
        date_from, date_to = today, today + timedelta(days=7)
    elif "this month" in lowered:
        date_from, date_to = _month_bounds(today)
    elif "next month" in lowered:
        next_month_date = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        date_from, date_to = _month_bounds(next_month_date)
    elif "next quarter" in lowered:
        date_from, date_to = _quarter_bounds(today, offset_quarters=1)
    elif "this quarter" in lowered:
        date_from, date_to = _quarter_bounds(today)
    elif "this year" in lowered:
        date_from, date_to = date(today.year, 1, 1), date(today.year, 12, 31)

    # "overdue"/"past due" is inherently a backward-looking status filter —
    # a forward date range would silently exclude every result if one was
    # picked up from unrelated wording elsewhere in the same query.
    if status == ObligationStatus.OVERDUE:
        date_from, date_to = None, today

    return CalendarQueryFilters(
        status=status, category=category, trigger_date_from=date_from, trigger_date_to=date_to
    )


async def run_calendar_query(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contract_id: uuid.UUID | None,
    filters: CalendarQueryFilters,
) -> ChatAnswer:
    """The calendar-query intent's whole answer path (plan §2 diagram):
    filters parsed by `parse_calendar_query` become ordinary SQLAlchemy
    predicates against `obligations`, org-scoped exactly like every other
    query in this system — there is no LLM call and no free-text
    retrieval here at all, so there's nothing for the faithfulness
    guardrail to check; the structured data *is* the grounding. Each
    result becomes its own numbered citation back to the obligation's
    source contract, when the obligation actually has a source_chunk_id
    (synthetic/demo obligations may not)."""
    query = (
        select(Obligation)
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(Contract.org_id == org_id)
        .options(selectinload(Obligation.contract))
    )
    if contract_id is not None:
        query = query.where(Obligation.contract_id == contract_id)
    if filters.status is not None:
        query = query.where(Obligation.status == filters.status)
    if filters.category is not None:
        query = query.where(Obligation.category == filters.category)
    if filters.trigger_date_from is not None:
        query = query.where(Obligation.trigger_date >= filters.trigger_date_from)
    if filters.trigger_date_to is not None:
        query = query.where(Obligation.trigger_date <= filters.trigger_date_to)
    query = query.order_by(Obligation.trigger_date.asc().nullslast()).limit(_MAX_RESULTS)

    obligations = list((await session.execute(query)).scalars().all())
    if not obligations:
        return ChatAnswer(
            answer_text="No obligations matched that calendar query.",
            citations=[],
            confidence="high",
        )

    lines: list[str] = []
    citations: list[ChatCitation] = []
    for i, obligation in enumerate(obligations, start=1):
        due = obligation.trigger_date.isoformat() if obligation.trigger_date else "no fixed date"
        lines.append(
            f"[{i}] {obligation.category.value} — {obligation.description} "
            f"(due {due}, status: {obligation.status.value}) — {obligation.contract.title}"
        )
        if obligation.source_chunk_id is not None:
            citations.append(
                ChatCitation(
                    ref_number=i,
                    source_chunk_id=obligation.source_chunk_id,
                    contract_id=obligation.contract_id,
                    contract_title=obligation.contract.title,
                    snippet=obligation.raw_source_text[:280] if obligation.raw_source_text else "",
                )
            )

    return ChatAnswer(answer_text="\n".join(lines), citations=citations, confidence="high")
