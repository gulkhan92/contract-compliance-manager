import math

from app.services.embeddings import EMBEDDING_DIM, embed_text, embed_texts
from app.services.similarity import cosine_similarity


def test_embed_text_returns_a_vector_of_the_expected_dimension() -> None:
    vector = embed_text("This Agreement renews automatically for one year.")
    assert len(vector) == EMBEDDING_DIM


def test_embeddings_are_l2_normalized() -> None:
    vector = embed_text("Either party may terminate this Agreement for convenience.")
    norm = math.sqrt(sum(x * x for x in vector))
    assert math.isclose(norm, 1.0, abs_tol=1e-4)


def test_embed_texts_preserves_order_and_count() -> None:
    texts = ["First paragraph.", "Second paragraph.", "Third paragraph."]
    vectors = embed_texts(texts)
    assert len(vectors) == len(texts)


def test_embed_texts_empty_list_returns_empty_list() -> None:
    assert embed_texts([]) == []


def test_semantically_similar_sentences_score_higher_than_unrelated_ones() -> None:
    renewal_a = embed_text(
        "This Agreement shall automatically renew for successive one-year terms."
    )
    renewal_b = embed_text(
        "The term of this Agreement will extend annually unless either party objects."
    )
    unrelated = embed_text("The cat sat on the mat in the warm afternoon sun.")

    similar_score = cosine_similarity(renewal_a, renewal_b)
    dissimilar_score = cosine_similarity(renewal_a, unrelated)

    assert similar_score > dissimilar_score
