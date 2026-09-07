import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContractStatus, ContractType, UserRole
from app.db.models import Contract, Organization, User
from app.services.chat.contract_matching import resolve_mentioned_contract_ids


async def _make_org_with_contracts(
    db_session: AsyncSession, *, titles: list[str]
) -> tuple[Organization, dict[str, uuid.UUID]]:
    org = Organization(name="Matching Test Org")
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

    ids_by_title: dict[str, list[uuid.UUID]] = {}
    for title in titles:
        contract = Contract(
            org_id=org.id,
            uploaded_by=user.id,
            title=title,
            contract_type=ContractType.OTHER,
            original_filename="test.pdf",
            storage_path="storage/test.pdf",
            file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=ContractStatus.ACTIVE,
        )
        db_session.add(contract)
        await db_session.flush()
        ids_by_title.setdefault(title, []).append(contract.id)

    # Flatten for convenience where titles are unique in a given test.
    flat = {title: ids[0] for title, ids in ids_by_title.items() if len(ids) == 1}
    return org, flat


@pytest.mark.asyncio
async def test_matches_a_short_title_by_its_one_significant_word(
    db_session: AsyncSession,
) -> None:
    org, ids = await _make_org_with_contracts(db_session, titles=["CO-BRANDING AGREEMENT"])

    matched = await resolve_mentioned_contract_ids(
        db_session,
        org_id=org.id,
        query_text="What is the termination notice period in the Co-Branding Agreement?",
    )

    assert matched == [ids["CO-BRANDING AGREEMENT"]]


@pytest.mark.asyncio
async def test_requires_every_significant_word_for_a_multiword_title(
    db_session: AsyncSession,
) -> None:
    org, ids = await _make_org_with_contracts(
        db_session, titles=["PRODUCT DEVELOPMENT AND CO-BRANDING AGREEMENT"]
    )

    # Mentions two of the three significant words (product, development)
    # but not "branding" — must not match; this is the exact false-
    # positive shape a looser bag-of-words match would wrongly catch.
    matched = await resolve_mentioned_contract_ids(
        db_session, org_id=org.id, query_text="Tell me about our product development timeline."
    )

    assert matched == []


@pytest.mark.asyncio
async def test_matches_multiword_title_when_all_significant_words_present(
    db_session: AsyncSession,
) -> None:
    org, ids = await _make_org_with_contracts(
        db_session, titles=["PRODUCT DEVELOPMENT AND CO-BRANDING AGREEMENT"]
    )

    matched = await resolve_mentioned_contract_ids(
        db_session,
        org_id=org.id,
        query_text="What does the Product Development and Co-Branding Agreement say about IP?",
    )

    assert matched == [ids["PRODUCT DEVELOPMENT AND CO-BRANDING AGREEMENT"]]


@pytest.mark.asyncio
async def test_duplicate_titles_all_match_not_just_one(db_session: AsyncSession) -> None:
    org = Organization(name="Duplicate Title Org")
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

    contract_ids = []
    for _ in range(2):
        contract = Contract(
            org_id=org.id,
            uploaded_by=user.id,
            title="CO-BRANDING AGREEMENT",
            contract_type=ContractType.OTHER,
            original_filename="test.pdf",
            storage_path="storage/test.pdf",
            file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=ContractStatus.ACTIVE,
        )
        db_session.add(contract)
        await db_session.flush()
        contract_ids.append(contract.id)

    matched = await resolve_mentioned_contract_ids(
        db_session, org_id=org.id, query_text="What's in the Co-Branding Agreement?"
    )

    assert set(matched) == set(contract_ids)


@pytest.mark.asyncio
async def test_no_mention_returns_empty_list_not_an_error(db_session: AsyncSession) -> None:
    org, _ids = await _make_org_with_contracts(db_session, titles=["CO-BRANDING AGREEMENT"])

    matched = await resolve_mentioned_contract_ids(
        db_session, org_id=org.id, query_text="What obligations are due this month?"
    )

    assert matched == []


@pytest.mark.asyncio
async def test_generic_words_alone_never_match(db_session: AsyncSession) -> None:
    org, _ids = await _make_org_with_contracts(db_session, titles=["CONTENT LICENSE AGREEMENT"])

    # Mentions "agreement" and "license" broadly, but not the
    # distinguishing word "content" — must not match.
    matched = await resolve_mentioned_contract_ids(
        db_session, org_id=org.id, query_text="What license agreements do we have?"
    )

    assert matched == []


@pytest.mark.asyncio
async def test_only_returns_contracts_from_the_requesting_org(db_session: AsyncSession) -> None:
    org_a, ids_a = await _make_org_with_contracts(db_session, titles=["CO-BRANDING AGREEMENT"])
    org_b = Organization(name="Other Org")
    db_session.add(org_b)
    await db_session.flush()
    user_b = User(
        org_id=org_b.id,
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        full_name="Test User B",
    )
    db_session.add(user_b)
    await db_session.flush()
    db_session.add(
        Contract(
            org_id=org_b.id,
            uploaded_by=user_b.id,
            title="CO-BRANDING AGREEMENT",
            contract_type=ContractType.OTHER,
            original_filename="test.pdf",
            storage_path="storage/test.pdf",
            file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=ContractStatus.ACTIVE,
        )
    )
    await db_session.flush()

    matched = await resolve_mentioned_contract_ids(
        db_session, org_id=org_a.id, query_text="What's in the Co-Branding Agreement?"
    )

    assert matched == [ids_a["CO-BRANDING AGREEMENT"]]
