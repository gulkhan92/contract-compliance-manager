"""Audit logging — every state-changing endpoint writes an entry here.

Auditability is a compliance requirement for this product, not optional
polish. See docs/CONTRACT_CLM_BUILD_PLAN.md §6.9.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def write_audit_log(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    session.add(
        AuditLog(
            org_id=org_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_=metadata,
            ip_address=ip_address,
        )
    )
    await session.flush()
