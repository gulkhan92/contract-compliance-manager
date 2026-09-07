import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.enums import AlertStatus, UserRole
from app.db.models import Alert, Contract, Obligation
from app.schemas.alert import AlertSummary
from app.services.audit import write_audit_log

router = APIRouter(prefix="/alerts", tags=["alerts"])

_EDITOR_ROLES = (UserRole.ADMIN, UserRole.LEGAL_OPS)


@router.get("", response_model=list[AlertSummary])
async def list_alerts(
    db: DbSession,
    current_user: CurrentUser,
    alert_status: Annotated[AlertStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Alert]:
    query = (
        select(Alert)
        .join(Obligation, Alert.obligation_id == Obligation.id)
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(Contract.org_id == current_user.org_id)
    )
    if alert_status is not None:
        query = query.where(Alert.status == alert_status)
    query = query.order_by(Alert.scheduled_for.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.patch("/{alert_id}/dismiss", response_model=AlertSummary)
async def dismiss_alert(db: DbSession, current_user: CurrentUser, alert_id: uuid.UUID) -> Alert:
    result = await db.execute(
        select(Alert)
        .join(Obligation, Alert.obligation_id == Obligation.id)
        .join(Contract, Obligation.contract_id == Contract.id)
        .where(Alert.id == alert_id, Contract.org_id == current_user.org_id)
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")

    is_recipient = alert.recipient_user_id == current_user.id
    if not is_recipient and current_user.role not in _EDITOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to dismiss this alert.",
        )

    alert.status = AlertStatus.CANCELLED
    await write_audit_log(
        db,
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="alert.dismiss",
        entity_type="alert",
        entity_id=alert.id,
    )
    await db.commit()
    return alert
