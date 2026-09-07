"""The chat pipeline orchestrator — plan §2's full diagram wired together:
guardrail-adjacent scope/intent routing, hybrid retrieval + reranking,
schema-constrained generation with citation binding, and one Langfuse
trace per turn spanning every stage (plan §8). Every branch produces a
`ChatAnswer` that's either fully cited or `insufficient_information` —
nothing in this module bypasses that contract.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import ChatIntent, ChatRole, ChatSessionScope
from app.schemas.chat import AnswerDiagnostics, ChatAnswer, RankedCandidate, RetrievalAttempt
from app.services import observability
from app.services.chat import calendar_query, guardrails
from app.services.chat.contract_matching import resolve_mentioned_contract_ids
from app.services.chat.generation import (
    ReferenceItem,
    generate_chat_answer,
    reference_item_from_chunk,
    reference_item_from_cuad_clause,
)
from app.services.chat.intent import classify_intent
from app.services.reranker import rerank
from app.services.retrieval import (
    ChunkFilters,
    hybrid_search_contract_chunks,
    hybrid_search_cuad_reference_clauses,
)

# How many reranked candidates (regardless of whether they cleared the
# relevance threshold) to keep for the diagnostics panel — enough to show
# a user why an answer was declined without persisting the whole overfetch
# batch on every insufficient_information turn.
_DIAGNOSTIC_CANDIDATE_PREVIEW_COUNT = 5

_OUT_OF_SCOPE_ANSWER = ChatAnswer(
    answer_text=(
        "I can only help with questions about your organization's contracts, "
        "obligations, and compliance calendar — I can't help with that."
    ),
    citations=[],
    confidence="insufficient_information",
)


@dataclass(frozen=True)
class ChatTurnResult:
    answer: ChatAnswer
    intent: ChatIntent
    tokens_used: int
    langfuse_trace_id: str | None
    # What was actually retrieved and passed to generation — empty for
    # the calendar-query and out-of-scope paths, which never retrieve.
    # Not used by the chat API itself; exists so scripts/run_rag_evaluation.py
    # can score context precision/recall against the real retrieved set
    # rather than re-deriving it with a second, possibly-diverging call.
    reference_items: list[ReferenceItem]
    # Only set for the domain_question/clause_benchmark branch, which is
    # the only one that retrieves anything — None for out_of_scope and
    # calendar_query turns. See AnswerDiagnostics.
    diagnostics: AnswerDiagnostics | None


async def _retrieve_reference_items(
    session: AsyncSession,
    *,
    question: str,
    filters: ChunkFilters,
    include_reference_corpus: bool,
    attempt_scope: Literal["narrowed", "unrestricted"],
    narrowed_to_contract_count: int,
) -> tuple[list[ReferenceItem], RetrievalAttempt]:
    settings = get_settings()
    with observability.trace_span("retrieval", question=question):
        # Over-fetch before reranking (plan §3.5): RRF fusion optimizes
        # for recall at a wider k, reranking then narrows to the precise
        # top few actually worth spending generation tokens on.
        overfetch_n = settings.chat_max_context_chunks * 2
        chunks = await hybrid_search_contract_chunks(
            session, query_text=question, filters=filters, top_n=overfetch_n
        )
        items = [
            reference_item_from_chunk(c)
            for c in chunks
            if not guardrails.contains_prompt_injection(c.raw_text)
        ]

        if include_reference_corpus:
            cuad_clauses = await hybrid_search_cuad_reference_clauses(
                session, query_text=question, top_n=overfetch_n
            )
            items += [
                reference_item_from_cuad_clause(c)
                for c in cuad_clauses
                if not guardrails.contains_prompt_injection(c.clause_text)
            ]

    empty_attempt = RetrievalAttempt(
        scope=attempt_scope,
        narrowed_to_contract_count=narrowed_to_contract_count,
        top_candidates=[],
    )
    if not items:
        return [], empty_attempt

    with observability.trace_span(
        "rerank", candidate_count=len(items), threshold=settings.chat_min_relevance_threshold
    ):
        scores = rerank(question, [item.text for item in items])
        ranked = sorted(zip(items, scores, strict=True), key=lambda pair: pair[1], reverse=True)
        relevant = [
            item for item, score in ranked if score >= settings.chat_min_relevance_threshold
        ]

    top_candidates = [
        RankedCandidate(
            contract_title=item.contract_title,
            snippet=item.text[:280],
            score=round(float(score), 4),
            passed_threshold=score >= settings.chat_min_relevance_threshold,
            is_reference_corpus=item.is_reference_corpus,
        )
        for item, score in ranked[:_DIAGNOSTIC_CANDIDATE_PREVIEW_COUNT]
    ]
    attempt = RetrievalAttempt(
        scope=attempt_scope,
        narrowed_to_contract_count=narrowed_to_contract_count,
        top_candidates=top_candidates,
    )
    return relevant[: settings.chat_max_context_chunks], attempt


async def run_chat_turn(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    scope: ChatSessionScope,
    scope_contract_id: uuid.UUID | None,
    question: str,
    history: list[tuple[ChatRole, str]],
) -> ChatTurnResult:
    """One full chat turn: classify -> route -> (retrieve+rerank ->
    generate) or (parse -> direct SQL) or (decline) -> trace. `scope`/
    `scope_contract_id` come from the ChatSession the message belongs to
    — a contract-scoped session restricts retrieval to that one
    contract's chunks; an org-wide session searches the whole org."""
    settings = get_settings()
    bounded_history = history[-settings.chat_max_history_messages :]

    with observability.trace_span(
        "chat_turn", org_id=str(org_id), scope=scope.value, question=question
    ):
        with observability.trace_span("intent_routing"):
            intent, _score = classify_intent(question)

        tokens_used = 0
        reference_items: list[ReferenceItem] = []
        diagnostics: AnswerDiagnostics | None = None

        if intent == ChatIntent.OUT_OF_SCOPE:
            answer = _OUT_OF_SCOPE_ANSWER

        elif intent == ChatIntent.CALENDAR_QUERY:
            with observability.trace_span("calendar_query"):
                filters = calendar_query.parse_calendar_query(question)
                answer = await calendar_query.run_calendar_query(
                    session, org_id=org_id, contract_id=scope_contract_id, filters=filters
                )

        else:
            include_reference_corpus = intent == ChatIntent.CLAUSE_BENCHMARK
            reference_items = []
            attempts: list[RetrievalAttempt] = []

            # Org-wide sessions only: if the question names a contract by
            # title (plan §3.4), try a search narrowed to just that
            # contract (or contracts — titles aren't guaranteed unique)
            # first. Never a hard restriction on its own — an empty
            # narrowed result falls through to the unrestricted search
            # below, so a spurious or overly-broad title match can only
            # ever degrade to today's unscoped behavior, never produce a
            # worse or wrong-contract answer. A contract-scoped session
            # already has its own certain scope and skips this.
            if scope == ChatSessionScope.ORGANIZATION:
                with observability.trace_span("contract_name_matching"):
                    mentioned_ids = await resolve_mentioned_contract_ids(
                        session, org_id=org_id, query_text=question
                    )
                if mentioned_ids:
                    narrowed_filters = ChunkFilters(org_id=org_id, contract_ids=mentioned_ids)
                    reference_items, narrowed_attempt = await _retrieve_reference_items(
                        session,
                        question=question,
                        filters=narrowed_filters,
                        include_reference_corpus=include_reference_corpus,
                        attempt_scope="narrowed",
                        narrowed_to_contract_count=len(mentioned_ids),
                    )
                    attempts.append(narrowed_attempt)

            if not reference_items:
                chunk_filters = ChunkFilters(org_id=org_id, contract_id=scope_contract_id)
                reference_items, unrestricted_attempt = await _retrieve_reference_items(
                    session,
                    question=question,
                    filters=chunk_filters,
                    include_reference_corpus=include_reference_corpus,
                    attempt_scope="unrestricted",
                    narrowed_to_contract_count=0,
                )
                attempts.append(unrestricted_attempt)

            with observability.trace_span(
                "generation", as_type="generation", reference_count=len(reference_items)
            ):
                answer, tokens_used = await generate_chat_answer(
                    session,
                    question=question,
                    history=bounded_history,
                    reference_items=reference_items,
                )

            if answer.confidence == "insufficient_information":
                # generation.py already knows its own guardrail reasons;
                # only the retrieval-stage causes (nothing retrieved vs.
                # retrieved-but-below-threshold) are decided here, since
                # generate_chat_answer has no visibility into *why*
                # reference_items came in empty.
                decline_reason = answer.decline_reason
                if decline_reason is None:
                    any_candidates = any(a.top_candidates for a in attempts)
                    decline_reason = (
                        "below_relevance_threshold" if any_candidates else "no_candidates_found"
                    )
                    answer = answer.model_copy(update={"decline_reason": decline_reason})
                decision_reason = decline_reason
            else:
                decision_reason = "answered"

            diagnostics = AnswerDiagnostics(
                decision_reason=decision_reason,
                relevance_threshold=settings.chat_min_relevance_threshold,
                attempts=attempts,
            )

        trace_id = observability.current_trace_id()

    return ChatTurnResult(
        answer=answer,
        intent=intent,
        tokens_used=tokens_used,
        langfuse_trace_id=trace_id,
        reference_items=reference_items,
        diagnostics=diagnostics,
    )
