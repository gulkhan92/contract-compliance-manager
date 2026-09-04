import math

from app.services.similarity import cosine_similarity


def test_identical_vectors_have_similarity_one() -> None:
    vector = [1.0, 2.0, 3.0]
    assert math.isclose(cosine_similarity(vector, vector), 1.0, rel_tol=1e-9)


def test_orthogonal_vectors_have_similarity_zero() -> None:
    assert math.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-9)


def test_opposite_vectors_have_similarity_negative_one() -> None:
    assert math.isclose(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0, rel_tol=1e-9)


def test_similarity_is_scale_invariant() -> None:
    a = [1.0, 2.0, 3.0]
    b = [2.0, 4.0, 6.0]  # same direction, different magnitude
    assert math.isclose(cosine_similarity(a, b), 1.0, rel_tol=1e-9)


def test_zero_vector_has_similarity_zero_rather_than_dividing_by_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
