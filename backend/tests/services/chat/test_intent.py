import pytest

from app.db.enums import ChatIntent
from app.services.chat.intent import classify_intent


@pytest.mark.parametrize(
    "query",
    [
        "What is the termination notice period in our NDA with Acme?",
        "Does our Rogers vendor agreement have a liability cap?",
        "Who is the counterparty on our master services agreement?",
    ],
)
def test_classifies_domain_questions(query: str) -> None:
    intent, score = classify_intent(query)

    assert intent == ChatIntent.DOMAIN_QUESTION
    assert score > 0


@pytest.mark.parametrize(
    "query",
    [
        "How does our liability cap compare to what's typical in similar agreements?",
        "Is a 90-day termination notice period standard for vendor contracts?",
        "Benchmark our indemnification clause against industry norms.",
    ],
)
def test_classifies_clause_benchmark_questions(query: str) -> None:
    intent, _score = classify_intent(query)

    assert intent == ChatIntent.CLAUSE_BENCHMARK


@pytest.mark.parametrize(
    "query",
    [
        "What obligations are due this month?",
        "Show me contracts expiring in the next 90 days.",
        "List overdue obligations across our portfolio.",
    ],
)
def test_classifies_calendar_queries(query: str) -> None:
    intent, _score = classify_intent(query)

    assert intent == ChatIntent.CALENDAR_QUERY


@pytest.mark.parametrize(
    "query",
    [
        "What's the weather like today?",
        "Write me a poem about autumn.",
        "Should I sue my landlord over this dispute?",
        "Tell me a joke.",
    ],
)
def test_classifies_out_of_scope_queries(query: str) -> None:
    intent, _score = classify_intent(query)

    assert intent == ChatIntent.OUT_OF_SCOPE


def test_low_confidence_match_is_forced_out_of_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "chat_scope_classifier_threshold", 1.1)

    intent, score = classify_intent("What is the termination notice period in our NDA?")

    assert intent == ChatIntent.OUT_OF_SCOPE
    assert score < 1.1
