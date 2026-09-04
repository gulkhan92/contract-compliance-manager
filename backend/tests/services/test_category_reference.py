from app.db.enums import ObligationCategory
from app.services.category_reference import best_matching_category, passes_semantic_filter
from app.services.embeddings import embed_text


def test_renewal_sentence_best_matches_renewal_category() -> None:
    embedding = embed_text(
        "This Agreement renews automatically for an additional one-year term "
        "unless either party gives 90 days written notice of non-renewal."
    )
    category, score = best_matching_category(embedding)
    assert category == ObligationCategory.RENEWAL
    assert score > 0.5


def test_governing_law_sentence_best_matches_governing_law_category() -> None:
    embedding = embed_text(
        "This Agreement shall be governed by the laws of the State of California."
    )
    category, _score = best_matching_category(embedding)
    assert category == ObligationCategory.GOVERNING_LAW


def test_confidentiality_sentence_best_matches_confidentiality_category() -> None:
    embedding = embed_text(
        "Each party shall keep the other party's confidential and proprietary "
        "information strictly confidential and shall not disclose it to third parties."
    )
    category, _score = best_matching_category(embedding)
    assert category == ObligationCategory.CONFIDENTIALITY


def test_unrelated_sentence_fails_the_semantic_filter() -> None:
    embedding = embed_text("The chef recommends pairing this dish with a light white wine.")
    assert not passes_semantic_filter(embedding)


def test_obligation_bearing_sentence_passes_the_semantic_filter() -> None:
    embedding = embed_text(
        "Either party may terminate this Agreement upon 60 days written notice."
    )
    assert passes_semantic_filter(embedding)
