import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.enums import ChatSessionScope, ContractStatus, ContractType, LLMProviderName, UserRole
from app.db.models import ChatMessage, ChatSession, Contract, ContractChunk, Organization, User
from app.services.embeddings import embed_text
from app.services.llm import orchestration as orchestration_module
from app.services.llm.base import LLMCompletionResult, LLMProvider


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_org_and_user(
    db_session: AsyncSession, *, org_name: str, email: str, role: UserRole = UserRole.ADMIN
) -> tuple[Organization, User]:
    org = Organization(name=org_name)
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id, email=email, hashed_password="irrelevant", role=role, full_name="Test User"
    )
    db_session.add(user)
    await db_session.flush()
    return org, user


async def _make_contract(
    db_session: AsyncSession, *, org_id: uuid.UUID, uploaded_by: uuid.UUID
) -> Contract:
    contract = Contract(
        org_id=org_id,
        uploaded_by=uploaded_by,
        title="Vendor Agreement",
        contract_type=ContractType.NDA,
        original_filename="vendor.pdf",
        storage_path="storage/vendor.pdf",
        file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=ContractStatus.ACTIVE,
    )
    db_session.add(contract)
    await db_session.flush()
    return contract


class _StubProvider(LLMProvider):
    def __init__(self, name: LLMProviderName, response_text: str) -> None:
        self.name = name
        self._response_text = response_text

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMCompletionResult:
        return LLMCompletionResult(text=self._response_text, tokens_used=10)


# --- Session CRUD ---


@pytest.mark.asyncio
async def test_create_organization_scoped_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user = await _make_org_and_user(db_session, org_name="Acme", email="a1@example.com")
    token = create_access_token(user_id=user.id, org_id=org.id, role=user.role)

    response = await client.post(
        "/api/v1/chat/sessions",
        json={"scope": "organization"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["scope"] == "organization"
    assert body["contract_id"] is None
    assert body["title"] == "New chat"


@pytest.mark.asyncio
async def test_create_contract_scoped_session_requires_contract_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user = await _make_org_and_user(db_session, org_name="Acme", email="a2@example.com")
    token = create_access_token(user_id=user.id, org_id=org.id, role=user.role)

    response = await client.post(
        "/api/v1/chat/sessions", json={"scope": "contract"}, headers=_auth_headers(token)
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_contract_scoped_session_rejects_another_orgs_contract(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, user_a = await _make_org_and_user(db_session, org_name="Org A", email="a3@example.com")
    org_b, user_b = await _make_org_and_user(db_session, org_name="Org B", email="b3@example.com")
    contract_b = await _make_contract(db_session, org_id=org_b.id, uploaded_by=user_b.id)
    token_a = create_access_token(user_id=user_a.id, org_id=org_a.id, role=user_a.role)

    response = await client.post(
        "/api/v1/chat/sessions",
        json={"scope": "contract", "contract_id": str(contract_b.id)},
        headers=_auth_headers(token_a),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_organization_scoped_session_rejects_contract_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user = await _make_org_and_user(db_session, org_name="Acme", email="a4@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=user.id)
    token = create_access_token(user_id=user.id, org_id=org.id, role=user.role)

    response = await client.post(
        "/api/v1/chat/sessions",
        json={"scope": "organization", "contract_id": str(contract.id)},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_sessions_only_returns_own_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user_a = await _make_org_and_user(db_session, org_name="Acme", email="a5@example.com")
    _org2, user_b = await _make_org_and_user(db_session, org_name="Acme", email="b5@example.com")
    db_session.add(
        ChatSession(
            org_id=org.id, user_id=user_a.id, scope=ChatSessionScope.ORGANIZATION, title="Mine"
        )
    )
    db_session.add(
        ChatSession(
            org_id=org.id, user_id=user_b.id, scope=ChatSessionScope.ORGANIZATION, title="Not mine"
        )
    )
    await db_session.flush()
    token_a = create_access_token(user_id=user_a.id, org_id=org.id, role=user_a.role)

    response = await client.get("/api/v1/chat/sessions", headers=_auth_headers(token_a))

    assert response.status_code == 200
    titles = [s["title"] for s in response.json()]
    assert titles == ["Mine"]


@pytest.mark.asyncio
async def test_get_session_404s_for_another_users_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user_a = await _make_org_and_user(db_session, org_name="Acme", email="a6@example.com")
    _org2, user_b = await _make_org_and_user(db_session, org_name="Acme", email="b6@example.com")
    other_session = ChatSession(
        org_id=org.id, user_id=user_b.id, scope=ChatSessionScope.ORGANIZATION, title="Not yours"
    )
    db_session.add(other_session)
    await db_session.flush()
    token_a = create_access_token(user_id=user_a.id, org_id=org.id, role=user_a.role)

    response = await client.get(
        f"/api/v1/chat/sessions/{other_session.id}", headers=_auth_headers(token_a)
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_session_404s_for_another_orgs_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, user_a = await _make_org_and_user(db_session, org_name="Org A", email="a7@example.com")
    org_b, user_b = await _make_org_and_user(db_session, org_name="Org B", email="b7@example.com")
    session_b = ChatSession(
        org_id=org_b.id, user_id=user_b.id, scope=ChatSessionScope.ORGANIZATION, title="Org B chat"
    )
    db_session.add(session_b)
    await db_session.flush()
    token_a = create_access_token(user_id=user_a.id, org_id=org_a.id, role=user_a.role)

    response = await client.get(
        f"/api/v1/chat/sessions/{session_b.id}", headers=_auth_headers(token_a)
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_session_removes_it(client: AsyncClient, db_session: AsyncSession) -> None:
    org, user = await _make_org_and_user(db_session, org_name="Acme", email="a8@example.com")
    session_row = ChatSession(
        org_id=org.id, user_id=user.id, scope=ChatSessionScope.ORGANIZATION, title="To delete"
    )
    db_session.add(session_row)
    await db_session.flush()
    token = create_access_token(user_id=user.id, org_id=org.id, role=user.role)

    delete_response = await client.delete(
        f"/api/v1/chat/sessions/{session_row.id}", headers=_auth_headers(token)
    )
    get_response = await client.get(
        f"/api/v1/chat/sessions/{session_row.id}", headers=_auth_headers(token)
    )

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_random_session_id_404s(client: AsyncClient, db_session: AsyncSession) -> None:
    org, user = await _make_org_and_user(db_session, org_name="Acme", email="a9@example.com")
    token = create_access_token(user_id=user.id, org_id=org.id, role=user.role)

    response = await client.get(
        f"/api/v1/chat/sessions/{uuid.uuid4()}", headers=_auth_headers(token)
    )

    assert response.status_code == 404


# --- Sending a message ---


@pytest.mark.asyncio
async def test_send_message_streams_grounded_answer_and_persists(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, user = await _make_org_and_user(db_session, org_name="Acme", email="c1@example.com")
    contract = await _make_contract(db_session, org_id=org.id, uploaded_by=user.id)
    chunk_text = "Either party may terminate this Agreement upon 60 days written notice."
    db_session.add(
        ContractChunk(
            contract_id=contract.id,
            paragraph_index=0,
            raw_text=chunk_text,
            embedding=embed_text(chunk_text),
            is_boilerplate=False,
            passed_prefilter=True,
        )
    )
    session_row = ChatSession(
        org_id=org.id, user_id=user.id, scope=ChatSessionScope.ORGANIZATION, title="Notice period"
    )
    db_session.add(session_row)
    await db_session.flush()

    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    response_text = (
        '{"answer_text": "The termination notice period is 60 days [1].", "confidence": "high"}'
    )
    monkeypatch.setattr(
        orchestration_module,
        "build_provider",
        lambda name: _StubProvider(name, response_text),
    )
    token = create_access_token(user_id=user.id, org_id=org.id, role=user.role)

    response = await client.post(
        f"/api/v1/chat/sessions/{session_row.id}/messages",
        json={"content": "What is the termination notice period?"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "60 days" in body
    assert '"type": "done"' in body
    assert '"confidence": "high"' in body

    messages = (
        await db_session.execute(
            ChatMessage.__table__.select().where(ChatMessage.session_id == session_row.id)
        )
    ).fetchall()
    assert len(messages) == 2  # user + assistant
    roles = {m.role for m in messages}
    assert roles == {"user", "assistant"}


@pytest.mark.asyncio
async def test_send_message_404s_for_another_users_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user_a = await _make_org_and_user(db_session, org_name="Acme", email="c2@example.com")
    _org2, user_b = await _make_org_and_user(db_session, org_name="Acme", email="c2b@example.com")
    other_session = ChatSession(
        org_id=org.id, user_id=user_b.id, scope=ChatSessionScope.ORGANIZATION, title="Not yours"
    )
    db_session.add(other_session)
    await db_session.flush()
    token_a = create_access_token(user_id=user_a.id, org_id=org.id, role=user_a.role)

    response = await client.post(
        f"/api/v1/chat/sessions/{other_session.id}/messages",
        json={"content": "Hello"},
        headers=_auth_headers(token_a),
    )

    assert response.status_code == 404


# --- Feedback ---


@pytest.mark.asyncio
async def test_update_feedback_on_own_message(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user = await _make_org_and_user(db_session, org_name="Acme", email="d1@example.com")
    session_row = ChatSession(
        org_id=org.id, user_id=user.id, scope=ChatSessionScope.ORGANIZATION, title="Chat"
    )
    db_session.add(session_row)
    await db_session.flush()
    message = ChatMessage(session_id=session_row.id, role="assistant", content="Some answer.")
    db_session.add(message)
    await db_session.flush()
    token = create_access_token(user_id=user.id, org_id=org.id, role=user.role)

    response = await client.patch(
        f"/api/v1/chat/messages/{message.id}/feedback",
        json={"feedback": "up"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["feedback"] == "up"


@pytest.mark.asyncio
async def test_update_feedback_404s_for_another_users_message(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user_a = await _make_org_and_user(db_session, org_name="Acme", email="d2@example.com")
    _org2, user_b = await _make_org_and_user(db_session, org_name="Acme", email="d2b@example.com")
    session_b = ChatSession(
        org_id=org.id, user_id=user_b.id, scope=ChatSessionScope.ORGANIZATION, title="Chat"
    )
    db_session.add(session_b)
    await db_session.flush()
    message = ChatMessage(session_id=session_b.id, role="assistant", content="Some answer.")
    db_session.add(message)
    await db_session.flush()
    token_a = create_access_token(user_id=user_a.id, org_id=org.id, role=user_a.role)

    response = await client.patch(
        f"/api/v1/chat/messages/{message.id}/feedback",
        json={"feedback": "down"},
        headers=_auth_headers(token_a),
    )

    assert response.status_code == 404


# --- Admin evaluation summary ---


@pytest.mark.asyncio
async def test_evaluation_summary_requires_admin_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, viewer = await _make_org_and_user(
        db_session, org_name="Acme", email="e1@example.com", role=UserRole.VIEWER
    )
    token = create_access_token(user_id=viewer.id, org_id=org.id, role=viewer.role)

    response = await client.get(
        "/api/v1/chat/admin/evaluation-summary", headers=_auth_headers(token)
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_evaluation_summary_aggregates_org_scoped_feedback(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, admin = await _make_org_and_user(db_session, org_name="Acme", email="e2@example.com")
    session_row = ChatSession(
        org_id=org.id, user_id=admin.id, scope=ChatSessionScope.ORGANIZATION, title="Chat"
    )
    db_session.add(session_row)
    await db_session.flush()
    db_session.add_all(
        [
            ChatMessage(session_id=session_row.id, role="assistant", content="A", feedback="up"),
            ChatMessage(session_id=session_row.id, role="assistant", content="B", feedback="down"),
            ChatMessage(
                session_id=session_row.id,
                role="assistant",
                content="C",
                confidence="insufficient_information",
            ),
        ]
    )
    await db_session.flush()
    token = create_access_token(user_id=admin.id, org_id=org.id, role=admin.role)

    response = await client.get(
        "/api/v1/chat/admin/evaluation-summary", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_assistant_messages"] == 3
    assert body["feedback_up_count"] == 1
    assert body["feedback_down_count"] == 1
    assert abs(body["insufficient_information_rate"] - (1 / 3)) < 1e-9
