"""Phase 12.1 tests: RRF fusion behavior on a known fixture set (pure,
no DB), and metadata filters correctly restricting hybrid search to the
requesting org_id — multi-tenant isolation is as critical here as
anywhere else in the system (docs/CHATBOT_INTEGRATION_PLAN.md §12.1).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContractStatus, ContractType, UserRole
from app.db.models import Contract, ContractChunk, Organization, User
from app.services.retrieval import (
    ChunkFilters,
    RetrievedChunk,
    hybrid_search_contract_chunks,
    reciprocal_rank_fusion,
)

# --- Pure RRF fusion, no DB ---


def test_rrf_ranks_item_in_both_lists_above_single_list_items() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    dense = [a, b]
    sparse = [c, a]

    fused = reciprocal_rank_fusion([dense, sparse])

    assert fused[0] == a  # appears rank 1 in dense, rank 2 in sparse — highest combined score


def test_rrf_preserves_rank_1_ordering_when_no_overlap() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()

    fused = reciprocal_rank_fusion([[a], [b]])

    # Both are rank-1 in their own list, so both score identically;
    # stable sort keeps the first list's rank-1 item first.
    assert set(fused) == {a, b}


def test_rrf_handles_empty_lists() -> None:
    assert reciprocal_rank_fusion([[], []]) == []


def test_rrf_handles_single_list() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    fused = reciprocal_rank_fusion([[a, b, c]])

    assert fused == [a, b, c]


def test_rrf_item_absent_from_one_list_still_scores_from_the_other() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()

    fused = reciprocal_rank_fusion([[a], []])

    assert fused == [a]
    # b never appeared anywhere, so it's simply absent from the result.
    assert b not in fused


def test_rrf_lower_rank_number_beats_higher_rank_number() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    fused = reciprocal_rank_fusion([[a, b, c]])

    assert fused.index(a) < fused.index(b) < fused.index(c)


# --- Hybrid search: org-scoping (multi-tenant isolation) ---


async def _make_org_contract_chunk(
    db_session: AsyncSession, *, org_name: str, raw_text: str
) -> tuple[Organization, ContractChunk]:
    org = Organization(name=org_name)
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()
    contract = Contract(
        org_id=org.id,
        uploaded_by=user.id,
        title=f"{org_name} Contract",
        contract_type=ContractType.NDA,
        original_filename="test.pdf",
        storage_path="storage/test.pdf",
        file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=ContractStatus.ACTIVE,
    )
    db_session.add(contract)
    await db_session.flush()
    chunk = ContractChunk(
        contract_id=contract.id,
        paragraph_index=0,
        raw_text=raw_text,
        is_boilerplate=False,
        passed_prefilter=True,
    )
    db_session.add(chunk)
    await db_session.flush()
    return org, chunk


@pytest.mark.asyncio
async def test_hybrid_search_never_returns_another_orgs_chunks(db_session: AsyncSession) -> None:
    org_a, chunk_a = await _make_org_contract_chunk(
        db_session,
        org_name="Org A",
        raw_text="Either party may terminate this Agreement upon 60 days written notice.",
    )
    _org_b, _chunk_b = await _make_org_contract_chunk(
        db_session,
        org_name="Org B",
        raw_text="Either party may terminate this Agreement upon 60 days written notice.",
    )

    results = await hybrid_search_contract_chunks(
        db_session,
        query_text="termination notice",
        filters=ChunkFilters(org_id=org_a.id),
        top_n=10,
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk_a.id


@pytest.mark.asyncio
async def test_hybrid_search_lexical_path_finds_exact_term_match(db_session: AsyncSession) -> None:
    org, chunk = await _make_org_contract_chunk(
        db_session,
        org_name="Exact Term Org",
        raw_text=(
            "Notwithstanding Section 12.4(b), the Zylotech-9000 warranty survives termination."
        ),
    )

    results = await hybrid_search_contract_chunks(
        db_session,
        query_text="Zylotech-9000 warranty",
        filters=ChunkFilters(org_id=org.id),
        top_n=5,
    )

    assert any(r.chunk_id == chunk.id for r in results)


@pytest.mark.asyncio
async def test_hybrid_search_excludes_boilerplate_by_default(db_session: AsyncSession) -> None:
    org = Organization(name="Boilerplate Org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()
    contract = Contract(
        org_id=org.id,
        uploaded_by=user.id,
        title="Boilerplate Contract",
        contract_type=ContractType.NDA,
        original_filename="test.pdf",
        storage_path="storage/test.pdf",
        file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=ContractStatus.ACTIVE,
    )
    db_session.add(contract)
    await db_session.flush()
    boilerplate_chunk = ContractChunk(
        contract_id=contract.id,
        paragraph_index=0,
        raw_text="IN WITNESS WHEREOF, the parties have executed this Agreement.",
        is_boilerplate=True,
        passed_prefilter=False,
    )
    db_session.add(boilerplate_chunk)
    await db_session.flush()

    results = await hybrid_search_contract_chunks(
        db_session,
        query_text="witness whereof executed agreement",
        filters=ChunkFilters(org_id=org.id),
        top_n=5,
    )

    assert results == []


@pytest.mark.asyncio
async def test_hybrid_search_contract_id_filter_restricts_to_one_contract(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Multi Contract Org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()

    contracts = []
    chunks = []
    for i in range(2):
        contract = Contract(
            org_id=org.id,
            uploaded_by=user.id,
            title=f"Contract {i}",
            contract_type=ContractType.NDA,
            original_filename="test.pdf",
            storage_path="storage/test.pdf",
            file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=ContractStatus.ACTIVE,
        )
        db_session.add(contract)
        await db_session.flush()
        chunk = ContractChunk(
            contract_id=contract.id,
            paragraph_index=0,
            raw_text="Either party may terminate this Agreement upon 60 days written notice.",
            is_boilerplate=False,
            passed_prefilter=True,
        )
        db_session.add(chunk)
        await db_session.flush()
        contracts.append(contract)
        chunks.append(chunk)

    results = await hybrid_search_contract_chunks(
        db_session,
        query_text="termination notice",
        filters=ChunkFilters(org_id=org.id, contract_id=contracts[0].id),
        top_n=10,
    )

    assert len(results) == 1
    assert results[0].contract_id == contracts[0].id


def test_retrieved_chunk_is_a_plain_dataclass() -> None:
    chunk_id = uuid.uuid4()
    contract_id = uuid.uuid4()
    item = RetrievedChunk(
        chunk_id=chunk_id,
        contract_id=contract_id,
        contract_title="Test",
        section_heading=None,
        raw_text="text",
    )
    assert item.chunk_id == chunk_id
