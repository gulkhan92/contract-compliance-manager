import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.contract import Contract
    from app.db.models.obligation import Obligation

EMBEDDING_DIM = 768  # BAAI/bge-base-en-v1.5


class ContractChunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "contract_chunks"
    __table_args__ = (
        Index(
            "ix_contract_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True
    )
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_heading: Mapped[str | None] = mapped_column(String(500))

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    is_boilerplate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passed_prefilter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    contract: Mapped["Contract"] = relationship(back_populates="chunks")
    obligations: Mapped[list["Obligation"]] = relationship(back_populates="source_chunk")
