import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_role
from app.db.enums import ObligationCategory, ObligationStatus, UserRole, RecurrenceType
from app.db.models import Contract, Obligation, User
from app.schemas.obligation import (
    CalendarEntry,
    ObligationCreate,
    ObligationDetail,
    ObligationSummary,
    ObligationUpdate,
)
from app.services.audit import write_audit_log
from app.services.obligation_dates import compute_alert_date, initial_obligation_status

router = APIRouter(prefix="/obligations", tags=["obligations"])

_EDITOR_ROLES = (UserRole.ADMIN, UserRole.LEGAL_OPS)

# Obligations that are done being tracked — never surfaced on the calendar,
# and no longer eligible for automatic status recalculation on edit.
_CLOSED_STATUSES = (ObligationStatus.RESOLVED, ObligationStatus.WAIVED)


def _to_summary(obligation: Obligation) -> ObligationSummary:
    return ObligationSummary(
        id=obligation.id,
        contract_id=obligation.contract_id,
        contract_title=obligation.contract.title,
        category=obligation.category,
        description=obligation.description,
        responsible_party=obligation.responsible_party,
        trigger_date=obligation.trigger_date,
        notice_period_days=obligation.notice_period_days,
        computed_alert_date=obligation.computed_alert_date,
        monetary_amount=obligation.monetary_amount,
        currency=obligation.currency,
        recurrence=obligation.recurrence,
        status=obligation.status,
        confidence_score=obligation.confidence_score,
        is_human_reviewed=obligation.is_human_reviewed,
        assigned_to=obligation.assigned_to,
        created_at=obligation.created_at,
        updated_at=obligation.updated_at,
    )


def _to_detail(obligation: Obligation) -> ObligationDetail:
    return ObligationDetail(
        **_to_summary(obligation).model_dump(),
        source_chunk_id=obligation.source_chunk_id,
        raw_source_text=obligation.raw_source_text,
    )


async def _get_org_obligation(
    db: DbSession, current_user: CurrentUser, obligation_id: uuid.UUID
) -> Obligation:
    result = await db.execute(
        select(Obligation)
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(Obligation.id == obligation_id, Contract.org_id == current_user.org_id)
        .options(selectinload(Obligation.contract))
    )
    obligation = result.scalar_one_or_none()
    if obligation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obligation not found.")
    return obligation


@router.get("", response_model=list[ObligationSummary])
async def list_obligations(
    db: DbSession,
    current_user: CurrentUser,
    category: Annotated[ObligationCategory | None, Query()] = None,
    obligation_status: Annotated[ObligationStatus | None, Query(alias="status")] = None,
    contract_id: Annotated[uuid.UUID | None, Query()] = None,
    assigned_to: Annotated[uuid.UUID | None, Query()] = None,
    trigger_date_from: Annotated[date | None, Query()] = None,
    trigger_date_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ObligationSummary]:
    query = (
        select(Obligation)
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(Contract.org_id == current_user.org_id)
        .options(selectinload(Obligation.contract))
    )
    if category is not None:
        query = query.where(Obligation.category == category)
    if obligation_status is not None:
        query = query.where(Obligation.status == obligation_status)
    if contract_id is not None:
        query = query.where(Obligation.contract_id == contract_id)
    if assigned_to is not None:
        query = query.where(Obligation.assigned_to == assigned_to)
    if trigger_date_from is not None:
        query = query.where(Obligation.trigger_date >= trigger_date_from)
    if trigger_date_to is not None:
        query = query.where(Obligation.trigger_date <= trigger_date_to)
    query = query.order_by(Obligation.trigger_date.asc().nullslast()).limit(limit).offset(offset)

    result = await db.execute(query)
    return [_to_summary(o) for o in result.scalars().all()]


@router.get("/calendar", response_model=list[CalendarEntry])
async def get_obligation_calendar(
    db: DbSession,
    current_user: CurrentUser,
    within_days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> list[CalendarEntry]:
    """Everything still actionable that's due within the window, plus
    anything already overdue — the data behind the "expiring in 30/60/90
    days" dashboard view (docs/CONTRACT_CLM_BUILD_PLAN.md §8)."""
    horizon = date.today() + timedelta(days=within_days)
    query = (
        select(Obligation)
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(
            Contract.org_id == current_user.org_id,
            Obligation.trigger_date.is_not(None),
            Obligation.trigger_date <= horizon,
            Obligation.status.not_in(_CLOSED_STATUSES),
        )
        .options(selectinload(Obligation.contract))
        .order_by(Obligation.trigger_date.asc())
    )
    result = await db.execute(query)
    return [CalendarEntry(**_to_summary(o).model_dump()) for o in result.scalars().all()]


@router.get("/{obligation_id}", response_model=ObligationDetail)
async def get_obligation(
    db: DbSession, current_user: CurrentUser, obligation_id: uuid.UUID
) -> ObligationDetail:
    obligation = await _get_org_obligation(db, current_user, obligation_id)
    return _to_detail(obligation)


@router.patch("/{obligation_id}", response_model=ObligationDetail)
async def update_obligation(
    db: DbSession,
    current_user: Annotated[User, Depends(require_role(*_EDITOR_ROLES))],
    obligation_id: uuid.UUID,
    body: ObligationUpdate,
) -> ObligationDetail:
    obligation = await _get_org_obligation(db, current_user, obligation_id)

    changes = body.model_dump(exclude_unset=True)
    if body.assigned_to is not None:
        assignee = await db.get(User, body.assigned_to)
        if assignee is None or assignee.org_id != current_user.org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_to must be a user in your organization.",
            )
    for field, value in changes.items():
        setattr(obligation, field, value)

    # Recompute the derived alert date whenever either input changed, using
    # the same plain-Python math as extraction — never delegated to the LLM.
    if "trigger_date" in changes or "notice_period_days" in changes:
        obligation.computed_alert_date = compute_alert_date(
            obligation.trigger_date, obligation.notice_period_days
        )
        # An explicit status in this same request wins; otherwise, a date
        # edit alone re-derives status from the new dates.
        if "status" not in changes:
            obligation.status = initial_obligation_status(
                obligation.trigger_date, obligation.computed_alert_date
            )

    # Reaching this endpoint at all — even an empty body — is a human
    # confirming the extraction, per docs/CONTRACT_CLM_BUILD_PLAN.md §7/§8.
    obligation.is_human_reviewed = True

    action = "obligation.waive" if changes.get("status") == ObligationStatus.WAIVED else (
        "obligation.edit" if changes else "obligation.confirm"
    )
    # JSON-safe re-serialization for the audit log — `changes` itself may
    # hold native date/UUID/enum objects the JSONB column can't accept.
    audit_metadata = body.model_dump(exclude_unset=True, mode="json") or None
    await write_audit_log(
        db,
        org_id=current_user.org_id,
        user_id=current_user.id,
        action=action,
        entity_type="obligation",
        entity_id=obligation.id,
        metadata=audit_metadata,
    )

    await db.commit()
    # updated_at is server-computed (onupdate=func.now()) — refresh just
    # that column rather than the whole object, so the already-loaded
    # `contract` relationship isn't expired back into a lazy load.
    await db.refresh(obligation, attribute_names=["updated_at"])
    return _to_detail(obligation)



# ---------- New Endpoints ----------

@router.post("/", response_model=ObligationDetail, status_code=status.HTTP_201_CREATED)
async def create_obligation(
    db: DbSession,
    current_user: Annotated[User, Depends(require_role(*_EDITOR_ROLES))],
    body: ObligationCreate,
) -> ObligationDetail:
    # Verify contract belongs to user's organization
    contract = await db.get(Contract, body.contract_id)
    if contract is None or contract.org_id != current_user.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")

    obligation = Obligation(
        contract_id=body.contract_id,
        category=body.category,
        description=body.description,
        responsible_party=body.responsible_party,
        trigger_date=body.trigger_date,
        notice_period_days=body.notice_period_days,
        monetary_amount=body.monetary_amount,
        currency=body.currency,
        recurrence=body.recurrence or RecurrenceType.NONE,
        assigned_to=body.assigned_to,
    )
    # Compute derived fields
    obligation.computed_alert_date = compute_alert_date(
        obligation.trigger_date, obligation.notice_period_days
    )
    obligation.status = initial_obligation_status(
        obligation.trigger_date, obligation.computed_alert_date
    )
    db.add(obligation)
    await db.flush()
    await write_audit_log(
        db,
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="obligation.create",
        entity_type="obligation",
        entity_id=obligation.id,
        metadata=body.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()
    await db.refresh(obligation)
    return _to_detail(obligation)


@router.delete("/{obligation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_obligation(
    db: DbSession,
    current_user: Annotated[User, Depends(require_role(*_EDITOR_ROLES))],
    obligation_id: uuid.UUID,
) -> None:
    obligation = await _get_org_obligation(db, current_user, obligation_id)
    await db.delete(obligation)
    await write_audit_log(
        db,
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="obligation.delete",
        entity_type="obligation",
        entity_id=obligation_id,
        metadata=None,
    )
    await db.commit()

