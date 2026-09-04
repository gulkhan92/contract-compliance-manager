"""Plain-Python cosine similarity — used for the in-memory category
comparison in category_reference.py. The pgvector-backed comparison for
clause_precedent_cache (dedup.py) uses the database's own cosine_distance
operator instead, since that comparison needs to run as a SQL query over
many stored rows, not a Python loop over values already in memory.
"""

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
