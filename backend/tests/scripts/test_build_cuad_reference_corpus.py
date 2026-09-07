"""extract_reference_clauses is pure parsing over a SQuAD-shaped dict — no
DB, no embedding model — so it's covered directly against small in-memory
fixtures rather than the real 40MB CUAD_v1.json."""

from typing import Any

from scripts.build_cuad_reference_corpus import extract_reference_clauses


def _qa(
    *, category: str, text: str = "", is_impossible: bool = False, answers: list[str] | None = None
) -> dict[str, Any]:
    if answers is None:
        answers = [text] if text else []
    return {
        "question": (
            f'Highlight the parts (if any) of this contract related to "{category}" '
            "that should be reviewed by a lawyer. Details: some description"
        ),
        "is_impossible": is_impossible,
        "answers": [{"text": a, "answer_start": 0} for a in answers],
    }


def _contract(title: str, qas: list[dict[str, Any]]) -> dict[str, Any]:
    return {"title": title, "paragraphs": [{"context": "irrelevant", "qas": qas}]}


def test_extracts_category_from_question_template() -> None:
    cuad_json = {
        "data": [
            _contract(
                "Contract A",
                [_qa(category="Governing Law", text="Laws of the State of Delaware apply here.")],
            )
        ]
    }

    rows = extract_reference_clauses(cuad_json)

    assert len(rows) == 1
    assert rows[0].category == "Governing Law"
    assert rows[0].source_contract_title == "Contract A"
    assert rows[0].clause_text == "Laws of the State of Delaware apply here."


def test_skips_impossible_questions() -> None:
    cuad_json = {
        "data": [_contract("Contract A", [_qa(category="Non-Compete", is_impossible=True)])]
    }

    assert extract_reference_clauses(cuad_json) == []


def test_skips_short_answers_below_minimum_length() -> None:
    cuad_json = {"data": [_contract("Contract A", [_qa(category="Cap On Liability", text="Yes")])]}

    assert extract_reference_clauses(cuad_json) == []


def test_dedupes_identical_category_text_pairs_across_answers() -> None:
    clause = "Each party shall indemnify the other against third-party claims."
    cuad_json = {
        "data": [
            _contract(
                "Contract A",
                [_qa(category="Indemnification", answers=[clause, clause])],
            )
        ]
    }

    rows = extract_reference_clauses(cuad_json)

    assert len(rows) == 1


def test_keeps_same_category_from_different_contracts() -> None:
    cuad_json = {
        "data": [
            _contract(
                "Contract A",
                [_qa(category="Governing Law", text="Governed by the laws of Delaware.")],
            ),
            _contract(
                "Contract B",
                [_qa(category="Governing Law", text="Governed by the laws of New York.")],
            ),
        ]
    }

    rows = extract_reference_clauses(cuad_json)

    assert len(rows) == 2
    assert {row.source_contract_title for row in rows} == {"Contract A", "Contract B"}


def test_ignores_malformed_question_with_no_category_match() -> None:
    cuad_json = {
        "data": [
            _contract(
                "Contract A",
                [
                    {
                        "question": "This question has no category quotes at all.",
                        "is_impossible": False,
                        "answers": [{"text": "Some clause text long enough.", "answer_start": 0}],
                    }
                ],
            )
        ]
    }

    assert extract_reference_clauses(cuad_json) == []
