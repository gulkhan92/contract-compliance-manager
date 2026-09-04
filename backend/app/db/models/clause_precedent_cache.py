import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.db.enums import ObligationCategory
from app.db.models.contract_chunk import EMBEDDING_DIM
from app.db.pg_types import obligation_category_enum


class ClausePrecedentCache(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Powers the LLM-call dedup step and the precedent-search feature — see
    docs/CONTRACT_CLM_BUILD_PLAN.md §3.3 and §9 (Precedent Search)."""

    __tablename__ = "clause_precedent_cache"
    __table_args__ = (
        Index(
            "ix_clause_precedent_cache_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    category: Mapped[ObligationCategory] = mapped_column(obligation_category_enum, nullable=False)
    cached_extraction: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
