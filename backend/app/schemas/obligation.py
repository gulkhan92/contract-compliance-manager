import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.db.enums import ObligationCategory, ObligationStatus, RecurrenceType


class ObligationSummary(BaseModel):
    id: uuid.UUID
    contract_id: uuid.UUID
    contract_title: str
    category: ObligationCategory
    description: str
    responsible_party: str | None
    trigger_date: date | None
    notice_period_days: int | None
    computed_alert_date: date | None
    monetary_amount: float | None
    currency: str | None
    recurrence: RecurrenceType
    status: ObligationStatus
    confidence_score: float | None
    is_human_reviewed: bool
    assigned_to: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ObligationCreate(BaseModel):
    """Schema for creating a new obligation via the API."""
    contract_id: uuid.UUID
    category: ObligationCategory
    description: str = Field(min_length=1, max_length=2000)
    responsible_party: str | None = Field(default=None, min_length=1, max_length=500)
    trigger_date: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0)
    monetary_amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    recurrence: RecurrenceType | None = None
    assigned_to: uuid.UUID | None = None
class ObligationDetail(ObligationSummary):
    source_chunk_id: uuid.UUID | None
    raw_source_text: str | None


class ObligationUpdate(BaseModel):
    """PATCH body covering every human-review action from
    docs/CONTRACT_CLM_BUILD_PLAN.md §8 (edit/confirm/waive) as one endpoint:
    an empty body just confirms the extraction as-is; setting `status` to
    `waived` (or any other value) records that decision explicitly;
    setting any other field corrects the extracted data. Only fields the
    caller actually sends are applied — see api/v1/obligations.py's use of
    `exclude_unset=True`. Calling this endpoint at all marks the obligation
    human-reviewed, since only editor/admin roles can reach it.
    """

    category: ObligationCategory | None = None
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    responsible_party: str | None = Field(default=None, min_length=1, max_length=500)
    trigger_date: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0)
    monetary_amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    recurrence: RecurrenceType | None = None
    status: ObligationStatus | None = None
    assigned_to: uuid.UUID | None = None


class CalendarEntry(ObligationSummary):
    pass


class DashboardSummary(BaseModel):
    at_risk_count: int
    overdue_count: int
    upcoming_this_month_count: int
    # Summed per currency rather than a single number — summing across
    # mixed currencies would silently produce a meaningless total.
    total_active_contract_value: dict[str, float]
