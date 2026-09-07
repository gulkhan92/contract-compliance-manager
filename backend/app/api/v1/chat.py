"""Chat session/message endpoints (plan §10). Every read/write is scoped
to the requesting user's own sessions within their own org — chat history
is private to the user who created it, not shared org-wide, matching the
plan's own "GET /chat/sessions # list current user's sessions" wording.

The message-send endpoint streams its response, but only *after* running
the full pipeline (retrieval -> generation -> faithfulness guardrail)
server-side: plan §4/§6.2 require that nothing reaches the client until
it's been citation-bound and guardrail-checked, which is fundamentally at
odds with true token-by-token streaming straight from the LLM. What's
streamed is the already-validated final answer, delivered in chunks so
the frontend can still render it incrementally, followed by one final
event carrying the structured citations/confidence/intent — see
send_message below.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_role
from app.core.config import get_settings
from app.core.rate_limit import chat_rate_limit_key, limiter
from app.db.enums import (
    ChatConfidence,
    ChatFeedback,
    ChatIntent,
    ChatRole,
    ChatSessionScope,
    UserRole,
)
from app.db.models import ChatMessage, ChatSession, Contract, User
from app.schemas.chat import (
    ChatFeedbackUpdate,
    ChatMessageCreate,
    ChatMessageSummary,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionSummary,
    EvaluationSummary,
)
from app.services import observability
from app.services.chat.evaluation import load_latest_eval_result
from app.services.chat.pipeline import run_chat_turn

router = APIRouter(prefix="/chat", tags=["chat"])

_STREAM_CHUNK_SIZE = 40


async def _get_own_session(
    db: AsyncSession, current_user: User, session_id: uuid.UUID
) -> ChatSession:
    session_row = await db.get(ChatSession, session_id)
    if (
        session_row is None
        or session_row.org_id != current_user.org_id
        or session_row.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found."
        )
    return session_row


@router.post("/sessions", response_model=ChatSessionSummary, status_code=status.HTTP_201_CREATED)
async def create_session(
    db: DbSession, current_user: CurrentUser, body: ChatSessionCreate
) -> ChatSession:
    if body.scope == ChatSessionScope.CONTRACT:
        if body.contract_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contract_id is required when scope is 'contract'.",
            )
        contract = await db.get(Contract, body.contract_id)
        if contract is None or contract.org_id != current_user.org_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")
        title = body.title or f"Chat about {contract.title}"
    else:
        if body.contract_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contract_id must not be set when scope is 'organization'.",
            )
        title = body.title or "New chat"

    session_row = ChatSession(
        org_id=current_user.org_id,
        user_id=current_user.id,
        scope=body.scope,
        contract_id=body.contract_id,
        title=title,
    )
    db.add(session_row)
    await db.commit()
    await db.refresh(session_row)
    return session_row


@router.get("/sessions", response_model=list[ChatSessionSummary])
async def list_sessions(db: DbSession, current_user: CurrentUser) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.org_id == current_user.org_id, ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    return list(result.scalars().all())


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(
    db: DbSession, current_user: CurrentUser, session_id: uuid.UUID
) -> ChatSession:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    session_row = result.scalar_one_or_none()
    if (
        session_row is None
        or session_row.org_id != current_user.org_id
        or session_row.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found."
        )
    return session_row


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(db: DbSession, current_user: CurrentUser, session_id: uuid.UUID) -> None:
    session_row = await _get_own_session(db, current_user, session_id)
    await db.delete(session_row)
    await db.commit()


def _sse_event(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_answer(
    assistant_message: ChatMessage,
    answer_text: str,
    citations: list[dict[str, object]],
    intent: ChatIntent,
    confidence: str,
    diagnostics: dict[str, object] | None,
) -> AsyncIterator[str]:
    for i in range(0, len(answer_text), _STREAM_CHUNK_SIZE):
        yield _sse_event({"type": "delta", "text": answer_text[i : i + _STREAM_CHUNK_SIZE]})
    yield _sse_event(
        {
            "type": "done",
            "message_id": str(assistant_message.id),
            "citations": citations,
            "confidence": confidence,
            "intent": intent.value,
            "retrieval_diagnostics": diagnostics,
        }
    )


@router.post("/sessions/{session_id}/messages")
@limiter.limit(lambda: get_settings().chat_rate_limit, key_func=chat_rate_limit_key)
async def send_message(
    request: Request,  # noqa: ARG001 — required by slowapi to key off the request
    db: DbSession,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: ChatMessageCreate,
) -> StreamingResponse:
    chat_session = await _get_own_session(db, current_user, session_id)

    history_result = await db.execute(
        select(ChatMessage.role, ChatMessage.content)
        .where(ChatMessage.session_id == chat_session.id, ChatMessage.role != ChatRole.SYSTEM)
        .order_by(ChatMessage.created_at)
    )
    history = [(role, content) for role, content in history_result.all()]

    db.add(ChatMessage(session_id=chat_session.id, role=ChatRole.USER, content=body.content))
    await db.flush()

    result = await run_chat_turn(
        db,
        org_id=current_user.org_id,
        scope=chat_session.scope,
        scope_contract_id=chat_session.contract_id,
        question=body.content,
        history=history,
    )

    citations_json = [c.model_dump(mode="json") for c in result.answer.citations]
    # Only persisted (and streamed) when the turn actually declined to
    # answer — a real cited answer has nothing to explain, and
    # out_of_scope/calendar_query turns never retrieve at all.
    diagnostics_json = (
        result.diagnostics.model_dump(mode="json")
        if result.diagnostics is not None
        and result.answer.confidence == "insufficient_information"
        else None
    )
    assistant_message = ChatMessage(
        session_id=chat_session.id,
        role=ChatRole.ASSISTANT,
        content=result.answer.answer_text,
        confidence=ChatConfidence(result.answer.confidence),
        intent=result.intent,
        citations=citations_json,
        retrieval_diagnostics=diagnostics_json,
        langfuse_trace_id=result.langfuse_trace_id,
    )
    db.add(assistant_message)
    chat_session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(assistant_message)
    observability.flush()

    return StreamingResponse(
        _stream_answer(
            assistant_message,
            result.answer.answer_text,
            citations_json,
            result.intent,
            result.answer.confidence,
            diagnostics_json,
        ),
        media_type="text/event-stream",
    )


@router.patch("/messages/{message_id}/feedback", response_model=ChatMessageSummary)
async def update_feedback(
    db: DbSession, current_user: CurrentUser, message_id: uuid.UUID, body: ChatFeedbackUpdate
) -> ChatMessage:
    result = await db.execute(
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatMessage.id == message_id,
            ChatSession.org_id == current_user.org_id,
            ChatSession.user_id == current_user.id,
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")

    message.feedback = body.feedback
    if message.langfuse_trace_id and body.feedback in (ChatFeedback.UP, ChatFeedback.DOWN):
        observability.record_feedback_score(
            trace_id=message.langfuse_trace_id, is_positive=body.feedback == ChatFeedback.UP
        )
    await db.commit()
    await db.refresh(message)
    return message


@router.get("/admin/evaluation-summary", response_model=EvaluationSummary)
async def get_evaluation_summary(
    db: DbSession, current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))]
) -> EvaluationSummary:
    base = (
        select(func.count())
        .select_from(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.org_id == current_user.org_id, ChatMessage.role == ChatRole.ASSISTANT)
    )
    total = await db.scalar(base) or 0
    up = await db.scalar(base.where(ChatMessage.feedback == ChatFeedback.UP)) or 0
    down = await db.scalar(base.where(ChatMessage.feedback == ChatFeedback.DOWN)) or 0
    insufficient = (
        await db.scalar(
            base.where(ChatMessage.confidence == ChatConfidence.INSUFFICIENT_INFORMATION)
        )
        or 0
    )

    latest = load_latest_eval_result()
    return EvaluationSummary(
        total_assistant_messages=total,
        feedback_up_count=up,
        feedback_down_count=down,
        insufficient_information_rate=(insufficient / total) if total else 0.0,
        offline_eval_run_at=latest.run_at if latest else None,
        offline_faithfulness=latest.faithfulness if latest else None,
        offline_answer_relevancy=latest.answer_relevancy if latest else None,
        offline_context_precision=latest.context_precision if latest else None,
        offline_context_recall=latest.context_recall if latest else None,
    )
