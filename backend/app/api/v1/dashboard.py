import calendar
import uuid
from datetime import date

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.db.enums import ContractStatus, ObligationStatus
from app.db.models import Contract, Obligation
from app.schemas.obligation import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _count_by_status(
    db: DbSession, *, org_id: uuid.UUID, obligation_status: ObligationStatus
) -> int:
    result = await db.execute(
        select(func.count(Obligation.id))
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(Contract.org_id == org_id, Obligation.status == obligation_status)
    )
    return result.scalar_one()


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(db: DbSession, current_user: CurrentUser) -> DashboardSummary:
    org_id = current_user.org_id

    at_risk_count = await _count_by_status(
        db, org_id=org_id, obligation_status=ObligationStatus.AT_RISK
    )
    overdue_count = await _count_by_status(
        db, org_id=org_id, obligation_status=ObligationStatus.OVERDUE
    )

    today = date.today()
    month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    upcoming_result = await db.execute(
        select(func.count(Obligation.id))
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(
            Contract.org_id == org_id,
            Obligation.status == ObligationStatus.UPCOMING,
            Obligation.trigger_date.is_not(None),
            Obligation.trigger_date >= today,
            Obligation.trigger_date <= month_end,
        )
    )
    upcoming_this_month_count = upcoming_result.scalar_one()

    value_result = await db.execute(
        select(Contract.currency, func.sum(Contract.contract_value))
        .where(
            Contract.org_id == org_id,
            Contract.status == ContractStatus.ACTIVE,
            Contract.contract_value.is_not(None),
            Contract.currency.is_not(None),
        )
        .group_by(Contract.currency)
    )
    total_active_contract_value = {
        currency: float(total) for currency, total in value_result.all()
    }

    return DashboardSummary(
        at_risk_count=at_risk_count,
        overdue_count=overdue_count,
        upcoming_this_month_count=upcoming_this_month_count,
        total_active_contract_value=total_active_contract_value,
    )
