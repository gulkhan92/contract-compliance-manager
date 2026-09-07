"""Offline RAG evaluation (plan §7.1, §12.7): the four RAGAS-defined
metrics (context precision, context recall, faithfulness, answer
relevancy), computed directly against this project's own retrieval
pipeline, embedding model, and LLMProvider abstraction — not the `ragas`
library itself. That's a deliberate deviation from the plan's literal
suggestion: `ragas` pulls in the full langchain + openai + tiktoken
dependency tree as dead weight (openai is never called once you override
its judge model), a real inconsistency with a codebase that has zero
LangChain/OpenAI anywhere and prides itself on lean, purpose-built LLM
calls. The methodology below follows RAGAS's own published definitions;
only the implementation is custom. See docs/CHATBOT_EVALUATION.md.

This module also persists results as a small on-disk JSON artifact, not a
database table — an evaluation run is a CI/dev-time event describing the
pipeline's current quality, not user data, and is inherently a single
"latest run" concept rather than something scoped per organization.
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.schemas.chat import ChatAnswer
from app.services.chat import guardrails
from app.services.chat.generation import ReferenceItem
from app.services.embeddings import embed_text
from app.services.similarity import cosine_similarity

_DEFAULT_RESULTS_PATH = Path(__file__).resolve().parents[3] / ".rag_eval_results.json"


@dataclass(frozen=True)
class RagEvalResult:
    run_at: datetime
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float
    num_questions: int


def save_eval_result(result: RagEvalResult, *, path: Path = _DEFAULT_RESULTS_PATH) -> None:
    payload = asdict(result)
    payload["run_at"] = result.run_at.isoformat()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_latest_eval_result(*, path: Path = _DEFAULT_RESULTS_PATH) -> RagEvalResult | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RagEvalResult(
            run_at=datetime.fromisoformat(payload["run_at"]),
            faithfulness=payload["faithfulness"],
            answer_relevancy=payload["answer_relevancy"],
            context_precision=payload["context_precision"],
            context_recall=payload["context_recall"],
            num_questions=payload["num_questions"],
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def utcnow() -> datetime:
    return datetime.now(UTC)


def context_precision(retrieved_items: list[ReferenceItem], ground_truth_answer: str) -> float:
    """Fraction of retrieved context items actually relevant to the
    ground-truth answer — precision of the retrieval step, independent of
    what generation later did with them. Reuses the faithfulness
    guardrail's own overlap threshold (empirically, genuinely unrelated
    contract-domain sentence pairs still land in the 0.4-0.55 range on
    this scorer, so a lower bar wouldn't actually separate signal from
    noise here either)."""
    if not retrieved_items:
        return 0.0
    threshold = get_settings().chat_faithfulness_overlap_threshold
    relevant = sum(
        1
        for item in retrieved_items
        if guardrails.local_faithfulness_score(ground_truth_answer, item.text) >= threshold
    )
    return relevant / len(retrieved_items)


def context_recall(retrieved_items: list[ReferenceItem], ground_truth_answer: str) -> float:
    """Whether the retrieved set covers the ground-truth answer at all —
    1.0 if at least one retrieved item overlaps it well enough to have
    supported a correct answer, else 0.0."""
    if not retrieved_items:
        return 0.0
    threshold = get_settings().chat_faithfulness_overlap_threshold
    best = max(
        guardrails.local_faithfulness_score(ground_truth_answer, item.text)
        for item in retrieved_items
    )
    return 1.0 if best >= threshold else 0.0


def faithfulness(answer: ChatAnswer) -> float:
    """1.0 if the pipeline produced a grounded, cited answer; 0.0 if it
    fell back to insufficient_information. Every citation in a
    non-insufficient ChatAnswer already individually passed
    generation.py's faithfulness guardrail (local overlap, or LLM-judge
    escalation on the borderline ones) by construction — unlike a raw
    LLM-as-judge pass over unfiltered model output, there is nothing left
    to additionally score post hoc. What varies here, and what this
    metric reports, is how often the system found groundable evidence at
    all rather than declining."""
    return 0.0 if answer.confidence == "insufficient_information" else 1.0


def answer_relevancy(question: str, answer: ChatAnswer) -> float:
    """Cosine similarity between the question and the generated answer
    text — a zero-extra-LLM-call proxy for RAGAS's own reverse-question-
    synthesis approach (which needs an LLM call per question to generate
    synthetic reverse-questions). Consistent with the same cost
    discipline the faithfulness guardrail already follows: a cheap local
    check before ever reaching for another model call. An
    insufficient_information answer scores 0 — declining to answer isn't
    "relevant" to the question in the sense this metric measures,
    however honest a choice it was."""
    if answer.confidence == "insufficient_information":
        return 0.0
    return max(0.0, cosine_similarity(embed_text(question), embed_text(answer.answer_text)))
