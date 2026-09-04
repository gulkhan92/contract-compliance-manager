import uuid
from datetime import datetime
from enum import Enum
from typing import TypeVar

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_E = TypeVar("_E", bound=Enum)


def pg_enum(enum_cls: type[_E], name: str) -> SAEnum:
    """A native PostgreSQL ENUM that persists `.value`, not `.name`.

    Our `str, Enum` classes (app.db.enums) intentionally use lowercase/UPPER
    values that don't always match the Python member name (e.g.
    `UserRole.ADMIN.value == "admin"`) — without `values_callable`, SQLAlchemy
    would persist the member *name* instead.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj])


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CreatedUpdatedAtMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
