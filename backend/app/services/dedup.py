"""Clause-level dedup against previously-extracted paragraphs, org-wide —
the third free filter stage in the token-minimization funnel (§3 step 3).
A near-duplicate paragraph (cosine similarity above threshold) reuses the
cached structured extraction instead of re-calling the LLM.

The cache this reads (`clause_precedent_cache`) is populated by Phase 5's
LLM extraction step, which doesn't exist yet — so nothing calls this
against a live upload today. It's built and tested now (against
synthetic cache rows) so Phase 5's extraction call is a straightforward
"check here first" addition rather than new infrastructure.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClausePrecedentCache

DEFAULT_DEDUP_SIMILARITY_THRESHOLD = 0.97


async def find_cached_extraction(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    embedding: list[float],
    threshold: float = DEFAULT_DEDUP_SIMILARITY_THRESHOLD,
) -> ClausePrecedentCache | None:
    """pgvector's `cosine_distance` is `1 - cosine_similarity`, so a
    similarity threshold becomes a maximum-distance filter."""
    max_distance = 1 - threshold
    distance = ClausePrecedentCache.embedding.cosine_distance(embedding)

    result = await session.execute(
        select(ClausePrecedentCache)
        .where(ClausePrecedentCache.org_id == org_id)
        .where(distance <= max_distance)
        .order_by(distance)
        .limit(1)
    )
    match = result.scalar_one_or_none()
    if match is not None:
        match.hit_count += 1
    return match
