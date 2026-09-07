"""Hybrid (dense + lexical) retrieval, fused with Reciprocal Rank Fusion —
the retrieval layer behind the chatbot's grounded question-answering and
clause-benchmark capabilities. See docs/CHATBOT_INTEGRATION_PLAN.md §3.

Dense-only vector search misses exact-term queries (section numbers,
defined terms, a counterparty's exact legal name); lexical-only search
misses conceptual questions ("clauses that limit our liability"). Both run
as ordinary Postgres queries — no new search service — and are combined
with RRF, which needs no score normalization across the two very different
scales (cosine similarity vs. `ts_rank_cd`).

Deliberately independent of any chat-specific code (intent routing,
generation, guardrails all live under services/chat/) so this module is
reusable wherever hybrid search over contract text is useful — today that's
the chatbot's domain-question and clause-benchmark intents; nothing here
assumes a chat session exists.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.enums import ContractType, ObligationCategory
from app.db.models import Contract, ContractChunk, CuadReferenceClause, Obligation
from app.services.embeddings import embed_text

DEFAULT_DENSE_CANDIDATES = 25
DEFAULT_SPARSE_CANDIDATES = 25
DEFAULT_FUSED_TOP_N = 8
# Standard RRF smoothing constant (Cormack, Clarke & Buettcher 2009) — large
# enough that a single list's rank-1 item doesn't automatically dominate,
# small enough that rank still matters more than raw list membership.
DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: list[list[uuid.UUID]], *, k: int = DEFAULT_RRF_K
) -> list[uuid.UUID]:
    """Merges any number of ranked ID lists into one fused ranking.
    `score(id) = sum(1 / (k + rank))` over every list the id appears in
    (1-indexed rank); an id absent from a list simply contributes nothing
    from it. Pure and side-effect-free so it's independently testable
    against fixed fixture lists, per the plan's Phase 12.1 test
    requirement, without touching a database."""
    scores: dict[uuid.UUID, float] = {}
    for ranked_list in ranked_lists:
        for rank, item_id in enumerate(ranked_list, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item_id: scores[item_id], reverse=True)


@dataclass(frozen=True)
class ChunkFilters:
    """Structured metadata constraints applied *alongside* hybrid search
    (as SQL predicates on both the dense and sparse candidate queries),
    never as a post-filter — narrowing after the fact would silently
    shrink recall below the top-N actually requested. `org_id` is
    mandatory and security-critical: identical multi-tenant scoping to
    every other query in this system."""

    org_id: uuid.UUID
    contract_id: uuid.UUID | None = None
    # A narrowed-but-not-certain set of candidate contracts (plan §3.4 —
    # e.g. the query named a contract by title) — distinct from
    # `contract_id`, which is a hard, certain restriction from the chat
    # session's own scope. See services/chat/contract_matching.py; the
    # caller is responsible for the "try narrowed, fall back to
    # unrestricted if nothing comes back" pattern that keeps a bad match
    # from ever making retrieval worse than not narrowing at all.
    contract_ids: list[uuid.UUID] | None = None
    contract_type: ContractType | None = None
    counterparty_name: str | None = None
    obligation_category: ObligationCategory | None = None
    expiration_date_from: date | None = None
    expiration_date_to: date | None = None
    exclude_boilerplate: bool = True


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    contract_id: uuid.UUID
    contract_title: str
    section_heading: str | None
    raw_text: str


def _filtered_chunk_query(filters: ChunkFilters) -> Select[tuple[uuid.UUID]]:
    query = (
        select(ContractChunk.id)
        .join(Contract, ContractChunk.contract_id == Contract.id)
        .where(Contract.org_id == filters.org_id)
    )
    if filters.contract_id is not None:
        query = query.where(ContractChunk.contract_id == filters.contract_id)
    if filters.contract_ids is not None:
        query = query.where(ContractChunk.contract_id.in_(filters.contract_ids))
    if filters.contract_type is not None:
        query = query.where(Contract.contract_type == filters.contract_type)
    if filters.counterparty_name is not None:
        query = query.where(Contract.counterparty_name.ilike(f"%{filters.counterparty_name}%"))
    if filters.expiration_date_from is not None:
        query = query.where(Contract.original_expiration_date >= filters.expiration_date_from)
    if filters.expiration_date_to is not None:
        query = query.where(Contract.original_expiration_date <= filters.expiration_date_to)
    if filters.exclude_boilerplate:
        query = query.where(ContractChunk.is_boilerplate.is_(False))
    if filters.obligation_category is not None:
        query = query.where(
            ContractChunk.id.in_(
                select(Obligation.source_chunk_id).where(
                    Obligation.category == filters.obligation_category,
                    Obligation.source_chunk_id.is_not(None),
                )
            )
        )
    return query


async def hybrid_search_contract_chunks(
    session: AsyncSession,
    *,
    query_text: str,
    filters: ChunkFilters,
    top_n: int = DEFAULT_FUSED_TOP_N,
    dense_candidates: int = DEFAULT_DENSE_CANDIDATES,
    sparse_candidates: int = DEFAULT_SPARSE_CANDIDATES,
) -> list[RetrievedChunk]:
    """Runs dense + lexical retrieval over one organization's
    `contract_chunks`, fuses via RRF, and returns the top `top_n` chunks
    in fused order with their parent contract's title attached."""
    query_embedding = await run_in_threadpool(embed_text, query_text)
    base = _filtered_chunk_query(filters)

    dense_query = (
        base.where(ContractChunk.embedding.is_not(None))
        .order_by(ContractChunk.embedding.cosine_distance(query_embedding))
        .limit(dense_candidates)
    )
    ts_query = func.websearch_to_tsquery("english", query_text)
    sparse_query = (
        base.where(ContractChunk.search_vector.op("@@")(ts_query))
        .order_by(func.ts_rank_cd(ContractChunk.search_vector, ts_query).desc())
        .limit(sparse_candidates)
    )

    dense_ids = list((await session.execute(dense_query)).scalars().all())
    sparse_ids = list((await session.execute(sparse_query)).scalars().all())
    fused_ids = reciprocal_rank_fusion([dense_ids, sparse_ids])[:top_n]
    if not fused_ids:
        return []

    rows = await session.execute(
        select(ContractChunk, Contract.title)
        .join(Contract, ContractChunk.contract_id == Contract.id)
        .where(ContractChunk.id.in_(fused_ids))
    )
    chunks_by_id = {chunk.id: (chunk, title) for chunk, title in rows.all()}
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            contract_id=chunk.contract_id,
            contract_title=title,
            section_heading=chunk.section_heading,
            raw_text=chunk.raw_text,
        )
        for chunk_id in fused_ids
        if (pair := chunks_by_id.get(chunk_id)) is not None
        for chunk, title in [pair]
    ]


@dataclass(frozen=True)
class RetrievedCuadClause:
    clause_id: uuid.UUID
    category: str
    source_contract_title: str
    clause_text: str


async def hybrid_search_cuad_reference_clauses(
    session: AsyncSession,
    *,
    query_text: str,
    category: str | None = None,
    top_n: int = DEFAULT_FUSED_TOP_N,
    dense_candidates: int = DEFAULT_DENSE_CANDIDATES,
    sparse_candidates: int = DEFAULT_SPARSE_CANDIDATES,
) -> list[RetrievedCuadClause]:
    """The clause-benchmark intent's retrieval path (plan §1/§3.2):
    identical hybrid-search-plus-RRF shape as `hybrid_search_contract_chunks`,
    against the global, non-org-scoped CUAD reference corpus instead —
    kept as a separate function rather than a generic one over both
    tables, since the two targets' columns and filters genuinely differ
    and a forced-generic abstraction would cost more clarity than it saves.
    """
    query_embedding = await run_in_threadpool(embed_text, query_text)
    base = select(CuadReferenceClause.id)
    if category is not None:
        base = base.where(CuadReferenceClause.category == category)

    dense_query = (
        base.where(CuadReferenceClause.embedding.is_not(None))
        .order_by(CuadReferenceClause.embedding.cosine_distance(query_embedding))
        .limit(dense_candidates)
    )
    ts_query = func.websearch_to_tsquery("english", query_text)
    sparse_query = (
        base.where(CuadReferenceClause.search_vector.op("@@")(ts_query))
        .order_by(func.ts_rank_cd(CuadReferenceClause.search_vector, ts_query).desc())
        .limit(sparse_candidates)
    )

    dense_ids = list((await session.execute(dense_query)).scalars().all())
    sparse_ids = list((await session.execute(sparse_query)).scalars().all())
    fused_ids = reciprocal_rank_fusion([dense_ids, sparse_ids])[:top_n]
    if not fused_ids:
        return []

    rows = await session.execute(
        select(CuadReferenceClause).where(CuadReferenceClause.id.in_(fused_ids))
    )
    clauses_by_id = {clause.id: clause for clause in rows.scalars().all()}
    return [
        RetrievedCuadClause(
            clause_id=clause.id,
            category=clause.category,
            source_contract_title=clause.source_contract_title,
            clause_text=clause.clause_text,
        )
        for clause_id in fused_ids
        if (clause := clauses_by_id.get(clause_id)) is not None
    ]
