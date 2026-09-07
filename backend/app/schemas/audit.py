import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    """Built field-by-field in the endpoint rather than via
    `model_validate(..., from_attributes=True)`: the ORM attribute is
    `AuditLog.metadata_` (`metadata` is reserved by SQLAlchemy's
    declarative base), so an automatic from-attributes mapping of a field
    literally named `metadata` would silently read the wrong thing."""

    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    metadata: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime
