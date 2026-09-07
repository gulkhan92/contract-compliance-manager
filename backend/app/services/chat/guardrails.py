"""Input, generation, and output guardrails (plan §6) — applied at three
points in the pipeline, not just at the end. Every check here is cheap
(regex or local embedding math) except the faithfulness guardrail's rare
LLM-judge escalation, which is deliberately batched into one call per
answer rather than one per sentence, matching the token-minimization
discipline established for extraction (docs/CONTRACT_CLM_BUILD_PLAN.md §3).
"""

import json
import logging
import re

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.embeddings import embed_text
from app.services.llm.orchestration import call_llm_with_fallback
from app.services.similarity import cosine_similarity

logger = logging.getLogger(__name__)

# --- 6.1 Input guardrails: prompt-injection screening over retrieved text ---
# Retrieved contract text is untrusted content (it's user-uploaded, and this
# pipeline's whole job is to feed it back into a prompt) — these patterns
# catch the common families of "ignore your instructions" attempts a
# malicious or poisoned document might contain. Deliberately a heuristic
# backstop, not the primary defense: the generation prompt itself
# structurally separates system instructions / retrieved context / user
# input and tells the model explicitly to ignore embedded instructions
# (see generation.py's SYSTEM_PROMPT) — this is the second layer, not the
# only one.
_INJECTION_PATTERNS = (
    re.compile(r"ignore (all |any )?(previous|prior|the above|earlier) instructions", re.I),
    re.compile(r"disregard (all |any )?(previous|prior|the above|earlier)", re.I),
    re.compile(r"new instructions\s*:", re.I),
    re.compile(r"system\s*:\s*you (are|must|should)", re.I),
    re.compile(r"you are now\s+\w+", re.I),
    re.compile(r"reveal (your|the) (system )?prompt", re.I),
    re.compile(r"print (your|the) (system )?instructions", re.I),
    re.compile(r"act as (if you|a) ", re.I),
    re.compile(r"\bDAN\b.{0,20}\bmode\b", re.I),
)


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


# --- 6.3 Output guardrails: no legal-advice framing ---
# Prescriptive ("you should terminate this contract") rather than
# descriptive ("this clause states...") phrasing. A match here means the
# whole answer is discarded in favor of the insufficient_information-style
# fallback (see pipeline.py) — fragile find/replace on an LLM's own
# sentence is not something to trust in a legal-domain product; either the
# answer is safe to show as generated, or it isn't shown at all.
_LEGAL_ADVICE_PATTERNS = (
    re.compile(r"\byou should (terminate|sue|breach|sign|cancel|waive|not sign)\b", re.I),
    re.compile(r"\byou must (terminate|sue|breach|sign|cancel|waive)\b", re.I),
    re.compile(r"\bi (recommend|advise) that you\b", re.I),
    re.compile(r"\bwe (recommend|advise) that you\b", re.I),
    re.compile(r"\bmy legal (opinion|advice) is\b", re.I),
    re.compile(r"\byou are legally (required|obligated) to\b", re.I),
    # Directing the user to a lawyer still reads as advice-giving rather
    # than descriptive, even though the intent behind it is caution.
    re.compile(r"\byou should (consult|hire)\b.{0,15}\blawyer\b", re.I),
)


def contains_legal_advice_framing(text: str) -> bool:
    return any(pattern.search(text) for pattern in _LEGAL_ADVICE_PATTERNS)


# --- 6.2 Generation guardrail: faithfulness / groundedness ---


def _lexical_overlap(a: str, b: str) -> float:
    """Jaccard similarity over lowercased word sets — catches verbatim/
    near-verbatim reuse that a paraphrase-tolerant embedding score might
    under-credit, without needing a second model."""
    words_a = set(re.findall(r"[a-z0-9]+", a.lower()))
    words_b = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def local_faithfulness_score(sentence: str, source_text: str) -> float:
    """The cheap, local, non-LLM check (§6.2) — the more generous of
    lexical overlap and embedding similarity, since either strong lexical
    or strong semantic overlap is real evidence of grounding, while
    requiring both at once would penalize legitimate paraphrasing."""
    lexical = _lexical_overlap(sentence, source_text)
    semantic = cosine_similarity(embed_text(sentence), embed_text(source_text))
    return max(lexical, semantic)


class _SentenceJudgment(BaseModel):
    sentence_index: int
    supported: bool


class _FaithfulnessJudgments(BaseModel):
    judgments: list[_SentenceJudgment] = Field(default_factory=list)


_JUDGE_SYSTEM_PROMPT = (
    "You are a strict fact-checker. For each numbered (SENTENCE, SOURCE) "
    "pair, decide whether SOURCE actually supports the factual claim made "
    "in SENTENCE. Return ONLY a single valid JSON object matching the "
    "provided JSON schema — no prose. A sentence is supported only if "
    "SOURCE contains the specific fact claimed, not merely a related topic."
)


def _build_judge_prompt(items: list[tuple[str, str]]) -> str:
    schema = _FaithfulnessJudgments.model_json_schema()
    pairs = "\n\n".join(
        f"[{i}] SENTENCE: {sentence}\n[{i}] SOURCE: {source}"
        for i, (sentence, source) in enumerate(items)
    )
    return f"JSON schema to match:\n{json.dumps(schema)}\n\nPairs:\n{pairs}"


async def _judge_faithfulness_batch(
    session: AsyncSession, *, items: list[tuple[str, str]]
) -> list[bool]:
    """One batched LLM call covering every borderline sentence in the
    answer, never one call per sentence. Fails closed (unsupported) if no
    provider is available — a faithfulness check that can't run is not
    grounds to let an unverified claim through in a legal-domain product.
    """
    if not items:
        return []
    outcome = await call_llm_with_fallback(
        session,
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        user_prompt=_build_judge_prompt(items),
        response_model=_FaithfulnessJudgments,
    )
    if outcome is None:
        logger.info("Faithfulness judge unavailable; failing %d sentence(s) closed.", len(items))
        return [False] * len(items)
    _, result, _tokens = outcome
    supported_by_index = {j.sentence_index: j.supported for j in result.judgments}
    return [supported_by_index.get(i, False) for i in range(len(items))]


async def check_faithfulness_batch(
    session: AsyncSession, *, sentence_source_pairs: list[tuple[str, str]]
) -> list[bool]:
    """The full two-stage check (§6.2) for a whole answer at once: the
    free local score first for every sentence, then exactly one batched
    LLM-judge call covering only the ones that didn't clear it locally."""
    threshold = get_settings().chat_faithfulness_overlap_threshold
    local_scores = [local_faithfulness_score(s, src) for s, src in sentence_source_pairs]
    results = [score >= threshold for score in local_scores]

    borderline_indices = [i for i, passed in enumerate(results) if not passed]
    if not borderline_indices:
        return results

    borderline_items = [sentence_source_pairs[i] for i in borderline_indices]
    judged = await _judge_faithfulness_batch(session, items=borderline_items)
    for local_index, supported in zip(borderline_indices, judged, strict=True):
        results[local_index] = supported
    return results
