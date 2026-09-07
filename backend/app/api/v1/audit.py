from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DbSession, require_role
from app.db.enums import UserRole
from app.db.models import AuditLog, User
from app.schemas.audit import AuditLogEntry

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=list[AuditLogEntry])
async def list_audit_log(
    db: DbSession,
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
    entity_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogEntry]:
    query = select(AuditLog).where(AuditLog.org_id == current_user.org_id)
    if entity_type is not None:
        query = query.where(AuditLog.entity_type == entity_type)
    query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return [
        AuditLogEntry(
            id=entry.id,
            user_id=entry.user_id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            metadata=entry.metadata_,
            ip_address=str(entry.ip_address) if entry.ip_address is not None else None,
            created_at=entry.created_at,
        )
        for entry in result.scalars().all()
    ]
