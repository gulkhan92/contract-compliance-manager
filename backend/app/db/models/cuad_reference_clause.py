from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 768  # BAAI/bge-base-en-v1.5, matching contract_chunks


class CuadReferenceClause(UUIDPrimaryKeyMixin, Base):
    """The clause-benchmark reference corpus (plan §1/§3.2, "secondary
    capability, reusing the same retrieval infrastructure"): one row per
    real, human-annotated clause answer from the 510-contract CUAD v1
    dataset (CC BY 4.0), across all ~41 CUAD clause categories.

    Deliberately global, not `org_id`-scoped like every other table in this
    system — this is shared reference/benchmark data (comparable to a
    fixed exemplar set, not a tenant's own uploaded documents), populated
    once via scripts/build_cuad_reference_corpus.py and read-only at
    request time. `category` holds CUAD's own 41-category taxonomy as a
    plain string rather than being forced into this app's 12-category
    `ObligationCategory` enum — the two taxonomies serve different
    purposes and don't map 1:1.
    """

    __tablename__ = "cuad_reference_clauses"
    __table_args__ = (
        Index(
            "ix_cuad_reference_clauses_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_cuad_reference_clauses_search_vector_gin", "search_vector", postgresql_using="gin"
        ),
    )

    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_contract_title: Mapped[str] = mapped_column(String(500), nullable=False)
    clause_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', clause_text)", persisted=True)
    )
