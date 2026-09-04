"""Fixed reference-embedding set per obligation category — the second,
still-free filter stage in the token-minimization funnel (§3 step 2 of
docs/CONTRACT_CLM_BUILD_PLAN.md). Each category is represented by a small
set of hand-written exemplar clauses illustrative of that category (in the
spirit of CUAD's own category definitions, §5.1 — not copied from CUAD's
licensed annotations), embedded once and cached.
"""

from functools import lru_cache

from app.db.enums import ObligationCategory
from app.services.embeddings import embed_texts
from app.services.similarity import cosine_similarity

DEFAULT_SEMANTIC_FILTER_THRESHOLD = 0.55

CATEGORY_EXEMPLARS: dict[ObligationCategory, list[str]] = {
    ObligationCategory.RENEWAL: [
        "This Agreement shall automatically renew for successive one-year "
        "terms unless either party provides written notice of non-renewal.",
        "The term of this Agreement will extend for an additional period "
        "unless terminated in accordance with this Section.",
    ],
    ObligationCategory.TERMINATION_NOTICE: [
        "Either party may terminate this Agreement upon sixty (60) days "
        "prior written notice to the other party.",
        "This Agreement may be terminated for convenience by either party "
        "upon written notice to the other party.",
    ],
    ObligationCategory.PAYMENT_MILESTONE: [
        "Customer shall pay Vendor the fees set forth in the applicable "
        "order form within thirty (30) days of the invoice date.",
        "Licensee shall remit a one-time license fee upon execution of "
        "this Agreement.",
    ],
    ObligationCategory.SLA_COMMITMENT: [
        "Provider shall maintain a monthly uptime percentage of at least "
        "99.9% for the Service.",
        "Provider shall use commercially reasonable efforts to respond to "
        "support requests within the response times set forth herein.",
    ],
    ObligationCategory.INDEMNIFICATION: [
        "Each party shall indemnify, defend, and hold harmless the other "
        "party from and against any third-party claims arising out of its "
        "breach of this Agreement.",
    ],
    ObligationCategory.CONFIDENTIALITY: [
        "Each party agrees to hold the other party's Confidential "
        "Information in strict confidence and not to disclose it to any "
        "third party.",
    ],
    ObligationCategory.NON_COMPETE: [
        "During the term of this Agreement and for twelve (12) months "
        "thereafter, neither party shall engage in a business that "
        "competes with the other party.",
    ],
    ObligationCategory.LIMITATION_OF_LIABILITY: [
        "In no event shall either party's aggregate liability under this "
        "Agreement exceed the total fees paid in the twelve (12) months "
        "preceding the claim.",
    ],
    ObligationCategory.GOVERNING_LAW: [
        "This Agreement shall be governed by and construed in accordance "
        "with the laws of the State of Delaware, without regard to its "
        "conflict of law principles.",
    ],
    ObligationCategory.AUDIT_RIGHTS: [
        "Licensor may, upon reasonable prior notice, audit Licensee's "
        "records to verify compliance with the terms of this Agreement.",
    ],
    ObligationCategory.DATA_PROTECTION: [
        "Each party shall comply with all applicable data protection "
        "laws, including the GDPR, in connection with its processing of "
        "personal data under this Agreement.",
    ],
    ObligationCategory.OTHER_OBLIGATION: [
        "Each party shall comply with all applicable laws and regulations "
        "in the performance of its obligations under this Agreement.",
    ],
}


@lru_cache
def _category_reference_embeddings() -> dict[ObligationCategory, list[list[float]]]:
    return {
        category: embed_texts(exemplars) for category, exemplars in CATEGORY_EXEMPLARS.items()
    }


def best_matching_category(embedding: list[float]) -> tuple[ObligationCategory, float]:
    """The category whose exemplar set is most similar, and that
    similarity (max cosine similarity across the category's exemplars)."""
    best_category: ObligationCategory | None = None
    best_score = -1.0
    for category, exemplar_embeddings in _category_reference_embeddings().items():
        score = max(cosine_similarity(embedding, ref) for ref in exemplar_embeddings)
        if score > best_score:
            best_score = score
            best_category = category
    assert best_category is not None  # CATEGORY_EXEMPLARS is never empty
    return best_category, best_score


def passes_semantic_filter(
    embedding: list[float], *, threshold: float = DEFAULT_SEMANTIC_FILTER_THRESHOLD
) -> bool:
    _category, score = best_matching_category(embedding)
    return score >= threshold
