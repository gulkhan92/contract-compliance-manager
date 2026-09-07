import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.enums import ContractStatus, UserRole
from app.db.models import Contract, ContractChunk, Organization, User
from app.services.embeddings import embed_text


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_org_and_admin(
    db_session: AsyncSession, *, org_name: str, email: str
) -> tuple[Organization, User]:
    org = Organization(name=org_name)
    db_session.add(org)
    await db_session.flush()
    admin = User(
        org_id=org.id,
        email=email,
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        full_name="Org Admin",
    )
    db_session.add(admin)
    await db_session.flush()
    return org, admin


async def _make_contract(
    db_session: AsyncSession, *, org_id: uuid.UUID, uploaded_by: uuid.UUID, title: str
) -> Contract:
    contract = Contract(
        org_id=org_id,
        uploaded_by=uploaded_by,
        title=title,
        original_filename="doc.pdf",
        storage_path="storage/doc.pdf",
        file_hash=uuid.uuid4().hex + "a" * 24,
        status=ContractStatus.ACTIVE,
    )
    db_session.add(contract)
    await db_session.flush()
    return contract


async def _make_chunk(
    db_session: AsyncSession, *, contract_id: uuid.UUID, raw_text: str, paragraph_index: int = 0
) -> ContractChunk:
    chunk = ContractChunk(
        contract_id=contract_id,
        paragraph_index=paragraph_index,
        raw_text=raw_text,
        embedding=embed_text(raw_text),
        passed_prefilter=True,
    )
    db_session.add(chunk)
    await db_session.flush()
    return chunk


@pytest.mark.asyncio
async def test_search_finds_semantically_similar_clause(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_admin(
        db_session, org_name="Acme", email="precedent1@example.com"
    )
    contract = await _make_contract(
        db_session, org_id=org.id, uploaded_by=admin.id, title="Vendor Agreement"
    )
    await _make_chunk(
        db_session,
        contract_id=contract.id,
        raw_text=(
            "Either party may terminate this Agreement by giving 90 days "
            "prior written notice to the other party."
        ),
        paragraph_index=0,
    )
    await _make_chunk(
        db_session,
        contract_id=contract.id,
        raw_text="All invoices are due and payable within thirty (30) days of receipt.",
        paragraph_index=1,
    )

    token = create_access_token(user_id=admin.id, org_id=org.id, role=UserRole.ADMIN)
    response = await client.get(
        "/api/v1/precedents/search",
        params={"q": "termination notice period"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["contract_id"] == str(contract.id)
    assert body[0]["contract_title"] == "Vendor Agreement"
    assert "terminate" in body[0]["raw_text"]
    assert 0.0 < body[0]["similarity"] <= 1.0
    assert body[0]["similarity"] > body[1]["similarity"]


@pytest.mark.asyncio
async def test_search_is_scoped_to_org(client: AsyncClient, db_session: AsyncSession) -> None:
    org_a, admin_a = await _make_org_and_admin(
        db_session, org_name="Org A", email="precedentA@example.com"
    )
    org_b, admin_b = await _make_org_and_admin(
        db_session, org_name="Org B", email="precedentB@example.com"
    )
    contract_b = await _make_contract(
        db_session, org_id=org_b.id, uploaded_by=admin_b.id, title="Org B Contract"
    )
    await _make_chunk(
        db_session,
        contract_id=contract_b.id,
        raw_text="Confidential information must be protected.",
    )

    token_a = create_access_token(user_id=admin_a.id, org_id=org_a.id, role=UserRole.ADMIN)
    response = await client.get(
        "/api/v1/precedents/search",
        params={"q": "confidentiality obligations"},
        headers=_auth_headers(token_a),
    )

    assert response.status_code == 200
    assert response.json() == []
