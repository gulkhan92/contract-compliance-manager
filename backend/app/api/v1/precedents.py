"""Semantic search over previously-ingested clause text, per
docs/CONTRACT_CLM_BUILD_PLAN.md §9/§12 Phase 9.

Searches `contract_chunks` rather than `clause_precedent_cache`: the cache
table (dedup.py) has no `contract_id` — it exists purely to short-circuit
repeat LLM calls, org-wide, and was never meant to be looked up by a human.
`contract_chunks` is the table that can actually satisfy "return ranked
results with source contract links" the way the plan describes this
feature, since every chunk already carries its own `contract_id`.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, DbSession
from app.db.models import Contract, ContractChunk
from app.schemas.precedent import PrecedentSearchResult
from app.services.embeddings import embed_text

router = APIRouter(prefix="/precedents", tags=["precedents"])


@router.get("/search", response_model=list[PrecedentSearchResult])
async def search_precedents(
    db: DbSession,
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=1000)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[PrecedentSearchResult]:
    query_embedding = await run_in_threadpool(embed_text, q)
    distance = ContractChunk.embedding.cosine_distance(query_embedding)

    result = await db.execute(
        select(ContractChunk, Contract.title, distance.label("distance"))
        .join(Contract, ContractChunk.contract_id == Contract.id)
        .where(Contract.org_id == current_user.org_id, ContractChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )

    return [
        PrecedentSearchResult(
            chunk_id=chunk.id,
            contract_id=chunk.contract_id,
            contract_title=contract_title,
            section_heading=chunk.section_heading,
            raw_text=chunk.raw_text,
            similarity=1 - distance_value,
        )
        for chunk, contract_title, distance_value in result.all()
    ]
