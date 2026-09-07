"""Local cross-encoder reranker — the second, still-free model in the
chatbot's retrieval pipeline (plan §3.5). Reorders the small RRF-fused
candidate set (top ~8-12 chunks) for precision before anything reaches the
LLM; unlike the bi-encoder used for embeddings, a cross-encoder scores the
query and each candidate jointly, which is far more precise at small `k`
but too slow to run over an entire corpus — exactly why it only ever sees
the already-narrowed fused candidates, never the full corpus directly.
"""

import math
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.core.config import get_settings


@lru_cache
def get_reranker_model() -> CrossEncoder:
    """`lru_cache` guarantees "loaded once" per process, same pattern as
    `embeddings.get_embedding_model` — the app's lifespan hook pre-warms
    this at startup; the cache is what makes calling it lazily elsewhere
    (tests, scripts) safe too."""
    return CrossEncoder(get_settings().reranker_model_name)  # type: ignore[no-any-return]


def rerank(query: str, candidates: list[str]) -> list[float]:
    """Returns one relevance score per candidate, same order as given, as
    a sigmoid-normalized [0, 1] value — the model's own logits are
    unbounded, and a bounded score is what lets a "minimum relevance"
    threshold (plan §4's insufficient_information fallback) mean the same
    thing call to call."""
    if not candidates:
        return []
    model = get_reranker_model()
    pairs = [[query, candidate] for candidate in candidates]
    raw_scores = model.predict(pairs)  # type: ignore[arg-type]
    return [1.0 / (1.0 + math.exp(-float(score))) for score in raw_scores]
