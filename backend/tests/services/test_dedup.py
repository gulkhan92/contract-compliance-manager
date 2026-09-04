import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ObligationCategory
from app.db.models import ClausePrecedentCache, Organization
from app.services.dedup import find_cached_extraction
from app.services.embeddings import EMBEDDING_DIM

# Deterministic synthetic vectors — dedup.py's cosine_distance query only
# cares about direction, not that these came from a real embedding model.
_UNIT_X = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
_UNIT_Y = [0.0, 1.0] + [0.0] * (EMBEDDING_DIM - 2)
# A small per-dimension perturbation accumulates across 767 dimensions —
# cosine_similarity(_UNIT_X, [0.999] + [0.01]*767) is only ~0.964, already
# below the 0.97 dedup threshold. This one keeps similarity to _UNIT_X
# above 0.99.
_NEAR_X = [0.9995] + [0.002] * (EMBEDDING_DIM - 1)


async def _make_org(db_session: AsyncSession) -> Organization:
    org = Organization(name="Dedup Test Org")
    db_session.add(org)
    await db_session.flush()
    return org


async def _cache_entry(
    db_session: AsyncSession,
    *,
    org_id: uuid.UUID,
    embedding: list[float],
    hit_count: int = 0,
) -> ClausePrecedentCache:
    entry = ClausePrecedentCache(
        org_id=org_id,
        text_hash="a" * 64,
        embedding=embedding,
        category=ObligationCategory.RENEWAL,
        cached_extraction={"category": "RENEWAL", "description": "cached"},
        hit_count=hit_count,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


@pytest.mark.asyncio
async def test_exact_match_is_found(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    await _cache_entry(db_session, org_id=org.id, embedding=_UNIT_X)

    match = await find_cached_extraction(db_session, org_id=org.id, embedding=_UNIT_X)

    assert match is not None


@pytest.mark.asyncio
async def test_near_duplicate_above_threshold_is_found(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    await _cache_entry(db_session, org_id=org.id, embedding=_UNIT_X)

    match = await find_cached_extraction(db_session, org_id=org.id, embedding=_NEAR_X)

    assert match is not None


@pytest.mark.asyncio
async def test_dissimilar_embedding_is_not_matched(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    await _cache_entry(db_session, org_id=org.id, embedding=_UNIT_X)

    match = await find_cached_extraction(db_session, org_id=org.id, embedding=_UNIT_Y)

    assert match is None


@pytest.mark.asyncio
async def test_match_is_scoped_to_org(db_session: AsyncSession) -> None:
    org_a = await _make_org(db_session)
    org_b = Organization(name="Other Org")
    db_session.add(org_b)
    await db_session.flush()
    await _cache_entry(db_session, org_id=org_a.id, embedding=_UNIT_X)

    match = await find_cached_extraction(db_session, org_id=org_b.id, embedding=_UNIT_X)

    assert match is None


@pytest.mark.asyncio
async def test_match_increments_hit_count(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    entry = await _cache_entry(db_session, org_id=org.id, embedding=_UNIT_X, hit_count=3)

    match = await find_cached_extraction(db_session, org_id=org.id, embedding=_UNIT_X)

    assert match is not None
    assert match.id == entry.id
    assert match.hit_count == 4
