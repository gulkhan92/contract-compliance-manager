"""Phase 12.3 orchestration tests: well-grounded answers, every
hallucination-shaped failure mode resolving to insufficient_information,
and malformed-output retry/fallback — mirroring test_extraction.py's
pattern (a canned _StubProvider monkeypatched in for
orchestration.build_provider, never a real LLM call).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import ChatRole, LLMProviderName
from app.services.chat.generation import ReferenceItem, generate_chat_answer
from app.services.llm import orchestration as orchestration_module
from app.services.llm.base import LLMCompletionResult, LLMProvider


class _StubProvider(LLMProvider):
    """Returns queued canned responses/exceptions in order, one per call."""

    def __init__(self, name: LLMProviderName, responses: list[object]) -> None:
        self.name = name
        self._responses = list(responses)
        self.calls = 0

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMCompletionResult:
        self.calls += 1
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return LLMCompletionResult(text=str(outcome), tokens_used=50)


def _reference_item(text: str, *, contract_title: str = "Test Contract") -> ReferenceItem:
    return ReferenceItem(
        contract_title=contract_title,
        text=text,
        contract_id=uuid.uuid4(),
        source_chunk_id=uuid.uuid4(),
        is_reference_corpus=False,
    )


@pytest.mark.asyncio
async def test_well_grounded_answer_produces_real_citations(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    response = (
        '{"answer_text": "The termination notice period is 60 days. [1]", '
        '"confidence": "high"}'
    )
    monkeypatch.setattr(
        orchestration_module, "build_provider", lambda name: _StubProvider(name, [response])
    )
    references = [
        _reference_item(
            "Either party may terminate this Agreement upon 60 days written notice.",
            contract_title="Acme NDA",
        )
    ]

    answer, tokens = await generate_chat_answer(
        db_session, question="What is the notice period?", history=[], reference_items=references
    )

    assert answer.confidence == "high"
    assert len(answer.citations) == 1
    assert answer.citations[0].ref_number == 1
    assert answer.citations[0].contract_title == "Acme NDA"
    assert answer.citations[0].contract_id == references[0].contract_id
    assert answer.decline_reason is None
    assert tokens == 50


@pytest.mark.asyncio
async def test_model_reported_insufficient_information_passes_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    response = (
        '{"answer_text": "I do not have enough information to answer that.", '
        '"confidence": "insufficient_information"}'
    )
    monkeypatch.setattr(
        orchestration_module, "build_provider", lambda name: _StubProvider(name, [response])
    )
    references = [_reference_item("Some unrelated clause text about audit rights.")]

    answer, _tokens = await generate_chat_answer(
        db_session, question="What is the notice period?", history=[], reference_items=references
    )

    assert answer.confidence == "insufficient_information"
    assert answer.citations == []
    assert answer.decline_reason == "llm_self_declined"


@pytest.mark.asyncio
async def test_uncited_substantive_claim_forces_insufficient_information(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    # A real-sounding factual claim with no [n] marker at all.
    response = (
        '{"answer_text": "The termination notice period is exactly sixty days long.", '
        '"confidence": "high"}'
    )
    monkeypatch.setattr(
        orchestration_module, "build_provider", lambda name: _StubProvider(name, [response])
    )
    references = [
        _reference_item("Either party may terminate this Agreement upon 60 days written notice.")
    ]

    answer, _tokens = await generate_chat_answer(
        db_session, question="What is the notice period?", history=[], reference_items=references
    )

    assert answer.confidence == "insufficient_information"
    assert answer.citations == []
    assert answer.decline_reason == "uncited_claim"


@pytest.mark.asyncio
async def test_invented_reference_number_forces_insufficient_information(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    # Only one reference item is supplied, but the model cites [5].
    response = '{"answer_text": "The notice period is 60 days. [5]", "confidence": "high"}'
    monkeypatch.setattr(
        orchestration_module, "build_provider", lambda name: _StubProvider(name, [response])
    )
    references = [
        _reference_item("Either party may terminate this Agreement upon 60 days written notice.")
    ]

    answer, _tokens = await generate_chat_answer(
        db_session, question="What is the notice period?", history=[], reference_items=references
    )

    assert answer.confidence == "insufficient_information"
    assert answer.decline_reason == "uncited_claim"  # an invalid ref number counts as uncited


@pytest.mark.asyncio
async def test_unfaithful_citation_forces_insufficient_information(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    # Cited correctly (marker resolves), but the claim isn't actually
    # supported by the referenced source text — a hallucinated fact
    # dressed up with a real-looking citation. Low local overlap escalates
    # to the LLM judge, which explicitly says it's unsupported.
    generation_response = (
        '{"answer_text": "The contract requires quarterly audits by an '
        'independent third party. [1]", "confidence": "high"}'
    )
    judge_response = '{"judgments": [{"sentence_index": 0, "supported": false}]}'
    stub = _StubProvider(LLMProviderName.GROQ, [generation_response, judge_response])
    monkeypatch.setattr(orchestration_module, "build_provider", lambda name: stub)
    references = [
        _reference_item("Employees must complete safety training within 30 days of hire.")
    ]

    answer, _tokens = await generate_chat_answer(
        db_session,
        question="Does this contract require audits?",
        history=[],
        reference_items=references,
    )

    assert answer.confidence == "insufficient_information"
    assert answer.decline_reason == "failed_faithfulness_check"
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_legal_advice_framing_forces_insufficient_information(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    response = (
        '{"answer_text": "You should terminate this contract immediately. [1]", '
        '"confidence": "high"}'
    )
    monkeypatch.setattr(
        orchestration_module, "build_provider", lambda name: _StubProvider(name, [response])
    )
    references = [_reference_item("Either party may terminate upon 60 days written notice.")]

    answer, _tokens = await generate_chat_answer(
        db_session, question="What should I do?", history=[], reference_items=references
    )

    assert answer.confidence == "insufficient_information"
    assert answer.decline_reason == "legal_advice_framing"


@pytest.mark.asyncio
async def test_malformed_json_triggers_one_corrective_retry(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    valid = '{"answer_text": "The notice period is 60 days. [1]", "confidence": "high"}'
    stub = _StubProvider(LLMProviderName.GROQ, ["{not valid json", valid])
    monkeypatch.setattr(orchestration_module, "build_provider", lambda name: stub)
    references = [
        _reference_item("Either party may terminate this Agreement upon 60 days written notice.")
    ]

    answer, tokens = await generate_chat_answer(
        db_session, question="What is the notice period?", history=[], reference_items=references
    )

    assert stub.calls == 2
    assert answer.confidence == "high"
    assert tokens == 100


@pytest.mark.asyncio
async def test_no_provider_available_falls_back_to_insufficient_information(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    references = [_reference_item("Some clause text.")]

    answer, tokens = await generate_chat_answer(
        db_session, question="Anything?", history=[], reference_items=references
    )

    assert answer.confidence == "insufficient_information"
    assert answer.decline_reason == "llm_unavailable"
    assert tokens == 0


@pytest.mark.asyncio
async def test_no_reference_items_skips_llm_call_entirely(db_session: AsyncSession) -> None:
    answer, tokens = await generate_chat_answer(
        db_session,
        question="Anything?",
        history=[(ChatRole.USER, "hi")],
        reference_items=[],
    )

    assert answer.confidence == "insufficient_information"
    # generate_chat_answer has no visibility into *why* retrieval came back
    # empty (nothing found vs. below threshold) — pipeline.py fills this in.
    assert answer.decline_reason is None
    assert tokens == 0
