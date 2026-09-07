import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.db.enums import ChatConfidence, ChatFeedback, ChatIntent, ChatRole, ChatSessionScope


DeclineReason = Literal[
    # Retrieval stage — decided in pipeline.py, before generation ever runs.
    "no_candidates_found",
    "below_relevance_threshold",
    # Generation stage — decided in generation.py's own guardrail chain.
    "llm_unavailable",
    "llm_self_declined",
    "legal_advice_framing",
    "uncited_claim",
    "failed_faithfulness_check",
]


class ChatCitation(BaseModel):
    """One numbered reference in an assistant answer, per plan §4 —
    `ref_number` matches an inline `[n]` marker in `answer_text`.

    `source_chunk_id`/`contract_id` are null for a clause-benchmark
    citation into the CUAD reference corpus (plan §3.2): that material
    isn't one of the requesting org's own contracts, so there's no
    document-viewer page for the frontend's "View in document" action to
    open — the citation is still real and shown, just not clickable.
    `is_reference_corpus` is what the frontend uses to tell the two apart
    without inferring it from a null check."""

    ref_number: int
    source_chunk_id: uuid.UUID | None
    contract_id: uuid.UUID | None
    contract_title: str
    snippet: str
    is_reference_corpus: bool = False


class ChatAnswer(BaseModel):
    """The LLM's raw structured output, parsed and validated before any of
    it reaches a user — never rendered as free-form text with inline
    citations the backend hasn't checked (plan §4)."""

    answer_text: str
    citations: list[ChatCitation] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "insufficient_information"]
    # Only ever set alongside confidence="insufficient_information" — which
    # of generation.py's guardrail branches (or, filled in afterward by
    # pipeline.py, which retrieval-stage outcome) actually produced the
    # decline. None for a real answer.
    decline_reason: DeclineReason | None = None


class RankedCandidate(BaseModel):
    """One reranked chunk from a retrieval attempt, kept regardless of
    whether it cleared `chat_min_relevance_threshold` — this is what
    powers the "here's what we found and why it wasn't used" panel on an
    insufficient_information answer. `score` is the same post-sigmoid
    [0,1] cross-encoder score the threshold itself is compared against."""

    contract_title: str
    snippet: str
    score: float
    passed_threshold: bool
    is_reference_corpus: bool = False


class RetrievalAttempt(BaseModel):
    """One call into `_retrieve_reference_items` (pipeline.py). An
    org-wide question naming a contract by title makes two attempts —
    "narrowed" first, "unrestricted" only if that came back empty — a
    contract-scoped session or an unnamed question makes exactly one,
    "unrestricted"."""

    scope: Literal["narrowed", "unrestricted"]
    # 0 for "unrestricted"; otherwise how many contracts the question's
    # wording matched by name (see contract_matching.py) and search was
    # narrowed to.
    narrowed_to_contract_count: int
    top_candidates: list[RankedCandidate]


class AnswerDiagnostics(BaseModel):
    """The full "why did the pipeline answer this way" trail for one
    turn — persisted on the assistant ChatMessage (and streamed in the
    SSE `done` event) only when confidence="insufficient_information", so
    a user who gets declined can see what was actually retrieved and
    which guardrail or threshold turned it away, rather than just the
    fixed apology string."""

    decision_reason: DeclineReason | Literal["answered"]
    relevance_threshold: float
    attempts: list[RetrievalAttempt]


class ChatSessionCreate(BaseModel):
    scope: ChatSessionScope
    # Required when scope=contract, forbidden when scope=organization —
    # enforced in api/v1/chat.py (a cross-field Pydantic validator can't
    # see the requesting user's org to also confirm the contract belongs
    # to it, so that check has to happen against the DB anyway).
    contract_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=255)


class ChatSessionSummary(BaseModel):
    id: uuid.UUID
    scope: ChatSessionScope
    contract_id: uuid.UUID | None
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageSummary(BaseModel):
    id: uuid.UUID
    role: ChatRole
    content: str
    confidence: ChatConfidence | None
    intent: ChatIntent | None
    citations: list[ChatCitation] | None
    feedback: ChatFeedback
    created_at: datetime
    # Only ever populated for an assistant message with
    # confidence="insufficient_information" — see AnswerDiagnostics.
    retrieval_diagnostics: AnswerDiagnostics | None = None

    model_config = {"from_attributes": True}


class ChatSessionDetail(ChatSessionSummary):
    messages: list[ChatMessageSummary] = Field(default_factory=list)


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ChatFeedbackUpdate(BaseModel):
    feedback: ChatFeedback


class EvaluationSummary(BaseModel):
    """Plan §7's admin quality view: online signal (real user feedback,
    always available) plus offline signal (the last CI-gated RAGAS-style
    run, when scripts/run_rag_evaluation.py has been run at least once —
    see docs/CHATBOT_EVALUATION.md). `offline_*` fields are null rather
    than fabricated when no evaluation run has ever been recorded."""

    total_assistant_messages: int
    feedback_up_count: int
    feedback_down_count: int
    insufficient_information_rate: float
    offline_eval_run_at: datetime | None
    offline_faithfulness: float | None
    offline_answer_relevancy: float | None
    offline_context_precision: float | None
    offline_context_recall: float | None
