"""Combined scope classification + intent routing (plan §2 diagram, §6.1).

The plan draws these as two separate boxes — a cheap embedding-similarity
scope gate ("reject clearly off-topic requests before any retrieval or
generation"), then a router splitting whatever's left into domain-question
/ clause-benchmark / calendar-query / out-of-scope. But `out_of_scope` is
already one of the router's four outcomes, so a separate upstream gate
would just be the same embedding-similarity classifier run twice against
overlapping label sets. This module collapses both into one multi-class
classifier over all four labels, reusing the exact exemplar-embedding
pattern already established in services/category_reference.py: an
out-of-scope match (or no match confident enough to trust) *is* the scope
guardrail's rejection — there's no second check that would ever disagree
with it.
"""

from functools import lru_cache

from app.core.config import get_settings
from app.db.enums import ChatIntent
from app.services.embeddings import embed_text, embed_texts
from app.services.similarity import cosine_similarity

INTENT_EXEMPLARS: dict[ChatIntent, list[str]] = {
    ChatIntent.DOMAIN_QUESTION: [
        "What is the termination notice period in our NDA with Acme Corp?",
        "What is the notice period required to terminate our vendor agreement?",
        "Does our vendor agreement with Rogers have a liability cap?",
        "Summarize the confidentiality obligations in the EuroMedia license.",
        "Which of our contracts have automatic renewal clauses?",
        "Who is the counterparty on our master services agreement?",
        "What governing law applies to our distributor agreement?",
        "Does this contract include an indemnification clause, and what does it cover?",
    ],
    ChatIntent.CLAUSE_BENCHMARK: [
        "How does our liability cap compare to what's typical in similar agreements?",
        "Is a 90-day termination notice period standard for vendor contracts?",
        "Benchmark our indemnification clause against industry norms.",
        "What's a typical non-compete duration in agreements like ours?",
        "Are our data protection terms stronger or weaker than usual?",
        "How unusual is it for a contract to lack a cap on liability?",
    ],
    ChatIntent.CALENDAR_QUERY: [
        "What obligations are due this month?",
        "Show me contracts expiring in the next 90 days.",
        "Which renewals are coming up next quarter?",
        "List overdue obligations across our portfolio.",
        "What's on the compliance calendar for December?",
        "Which obligations are still awaiting review?",
    ],
    ChatIntent.OUT_OF_SCOPE: [
        "What's the weather like today?",
        "Write me a poem about autumn.",
        "What's the capital of France?",
        "Should I sue my landlord over this dispute?",
        "Give me legal advice about my divorce.",
        "Can you help me write a Python script?",
        "Tell me a joke.",
        "Draft a new termination clause for me to use.",
        "What do you think of my business plan?",
    ],
}


@lru_cache
def _intent_exemplar_embeddings() -> dict[ChatIntent, list[list[float]]]:
    return {intent: embed_texts(exemplars) for intent, exemplars in INTENT_EXEMPLARS.items()}


def classify_intent(query: str) -> tuple[ChatIntent, float]:
    """The intent whose exemplar set best matches the query (max cosine
    similarity across that intent's exemplars), and that similarity. A
    best match that's still below `chat_scope_classifier_threshold` is
    forced to OUT_OF_SCOPE — the model correctly picked "closest," but
    "closest is still distant" is exactly what the scope guardrail exists
    to catch (plan §6.1)."""
    query_embedding = embed_text(query)
    best_intent: ChatIntent | None = None
    best_score = -1.0
    for intent, exemplar_embeddings in _intent_exemplar_embeddings().items():
        score = max(cosine_similarity(query_embedding, ref) for ref in exemplar_embeddings)
        if score > best_score:
            best_score = score
            best_intent = intent
    assert best_intent is not None  # INTENT_EXEMPLARS is never empty

    threshold = get_settings().chat_scope_classifier_threshold
    if best_score < threshold:
        return ChatIntent.OUT_OF_SCOPE, best_score
    return best_intent, best_score
