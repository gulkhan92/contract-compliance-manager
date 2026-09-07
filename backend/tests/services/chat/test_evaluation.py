import uuid

from app.schemas.chat import ChatAnswer
from app.services.chat.evaluation import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from app.services.chat.generation import ReferenceItem


def _reference_item(text: str) -> ReferenceItem:
    return ReferenceItem(
        contract_title="Test Contract",
        text=text,
        contract_id=uuid.uuid4(),
        source_chunk_id=uuid.uuid4(),
        is_reference_corpus=False,
    )


def _answer(confidence: str, text: str = "The notice period is 60 days.") -> ChatAnswer:
    return ChatAnswer(answer_text=text, citations=[], confidence=confidence)  # type: ignore[arg-type]


# --- context_precision ---


def test_context_precision_is_zero_for_no_retrieved_items() -> None:
    assert context_precision([], "Either party may terminate upon 60 days notice.") == 0.0


def test_context_precision_counts_only_relevant_items() -> None:
    relevant = _reference_item("Either party may terminate this Agreement upon 60 days notice.")
    irrelevant = _reference_item("Each party shall keep pricing information confidential.")

    precision = context_precision(
        [relevant, irrelevant], "Either party may terminate upon 60 days notice."
    )

    assert precision == 0.5


def test_context_precision_is_one_when_all_items_relevant() -> None:
    item = _reference_item("Either party may terminate this Agreement upon 60 days notice.")

    precision = context_precision([item, item], "Either party may terminate upon 60 days notice.")

    assert precision == 1.0


# --- context_recall ---


def test_context_recall_is_zero_for_no_retrieved_items() -> None:
    assert context_recall([], "Either party may terminate upon 60 days notice.") == 0.0


def test_context_recall_is_one_if_any_item_covers_the_ground_truth() -> None:
    relevant = _reference_item("Either party may terminate this Agreement upon 60 days notice.")
    irrelevant = _reference_item("Each party shall keep pricing information confidential.")

    recall = context_recall(
        [irrelevant, relevant], "Either party may terminate upon 60 days notice."
    )

    assert recall == 1.0


def test_context_recall_is_zero_if_nothing_covers_the_ground_truth() -> None:
    irrelevant = _reference_item("Each party shall keep pricing information confidential.")

    recall = context_recall([irrelevant], "Either party may terminate upon 60 days notice.")

    assert recall == 0.0


# --- faithfulness ---


def test_faithfulness_is_one_for_a_grounded_answer() -> None:
    assert faithfulness(_answer("high")) == 1.0
    assert faithfulness(_answer("medium")) == 1.0
    assert faithfulness(_answer("low")) == 1.0


def test_faithfulness_is_zero_for_insufficient_information() -> None:
    assert faithfulness(_answer("insufficient_information")) == 0.0


# --- answer_relevancy ---


def test_answer_relevancy_is_zero_for_insufficient_information() -> None:
    assert (
        answer_relevancy("What is the notice period?", _answer("insufficient_information")) == 0.0
    )


def test_answer_relevancy_is_high_for_a_directly_responsive_answer() -> None:
    answer = _answer("high", "The termination notice period is 60 days.")

    score = answer_relevancy("What is the termination notice period?", answer)

    assert score > 0.7


def test_answer_relevancy_is_lower_for_an_unrelated_answer() -> None:
    answer = _answer("high", "The governing law is the State of Delaware.")

    score = answer_relevancy("What is the termination notice period?", answer)

    assert score < 0.7
