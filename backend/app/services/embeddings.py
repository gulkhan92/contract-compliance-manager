"""Local sentence-embedding model — loaded once per process, reused
everywhere. Runs entirely on CPU, no API cost or rate limit, which is what
makes the semantic pre-filter (category_reference.py) and clause dedup
(dedup.py) stages of the token-minimization funnel free. See
docs/CONTRACT_CLM_BUILD_PLAN.md §4 and §12 Phase 4.
"""

import os
from functools import lru_cache

# huggingface_hub's newer "xet" chunked-transfer backend is less stable over
# constrained/proxied networks than a plain HTTP download; disabling it
# trades a little download speed for reliability, which matters more for a
# one-time model fetch than the last few percent of throughput. Must be set
# before sentence_transformers (which imports huggingface_hub) is imported.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from sentence_transformers import SentenceTransformer  # noqa: E402

from app.core.config import get_settings  # noqa: E402

EMBEDDING_DIM = 768  # must match the Vector(768) columns from the Phase 1 migration


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    """`lru_cache` is what actually guarantees "loaded once" — the
    lifespan hook in app.main pre-warms it at process startup for real
    deployments, but this cache is what makes that safe to call lazily
    too (e.g. in tests, which don't trigger ASGI lifespan events)."""
    return SentenceTransformer(get_settings().embedding_model_name)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_embedding_model()
    # BGE models are trained/evaluated for cosine similarity specifically
    # when their output is L2-normalized first.
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
