"""Langfuse tracing must be a true no-op whenever it isn't fully
configured — the chat pipeline's own tests never configure it, so if
these guarantees broke, every chat test in the suite would be silently
depending on unconfigured tracing behaving safely."""

from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.services import observability


@pytest.fixture(autouse=True)
def _clear_client_cache() -> Iterator[None]:
    observability._client.cache_clear()
    yield
    observability._client.cache_clear()


def test_disabled_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "langfuse_host", None)
    monkeypatch.setattr(get_settings(), "langfuse_public_key", None)
    monkeypatch.setattr(get_settings(), "langfuse_secret_key", None)

    assert observability.is_enabled() is False


def test_disabled_when_only_partially_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "langfuse_host", "http://localhost:3000")
    monkeypatch.setattr(get_settings(), "langfuse_public_key", "pk-test")
    monkeypatch.setattr(get_settings(), "langfuse_secret_key", None)

    assert observability.is_enabled() is False


def test_trace_span_is_a_harmless_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "langfuse_host", None)
    monkeypatch.setattr(get_settings(), "langfuse_public_key", None)
    monkeypatch.setattr(get_settings(), "langfuse_secret_key", None)

    ran = False
    with observability.trace_span("test-stage", foo="bar"):
        ran = True
    assert ran is True


def test_trace_span_still_propagates_exceptions_from_wrapped_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "langfuse_host", None)
    monkeypatch.setattr(get_settings(), "langfuse_public_key", None)
    monkeypatch.setattr(get_settings(), "langfuse_secret_key", None)

    with pytest.raises(ValueError, match="boom"), observability.trace_span("test-stage"):
        raise ValueError("boom")


def test_current_trace_id_is_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "langfuse_host", None)
    monkeypatch.setattr(get_settings(), "langfuse_public_key", None)
    monkeypatch.setattr(get_settings(), "langfuse_secret_key", None)

    assert observability.current_trace_id() is None


def test_record_feedback_score_is_a_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "langfuse_host", None)
    monkeypatch.setattr(get_settings(), "langfuse_public_key", None)
    monkeypatch.setattr(get_settings(), "langfuse_secret_key", None)

    # Must not raise even though no client/trace exists.
    observability.record_feedback_score(trace_id="does-not-exist", is_positive=True)


def test_flush_is_a_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "langfuse_host", None)
    monkeypatch.setattr(get_settings(), "langfuse_public_key", None)
    monkeypatch.setattr(get_settings(), "langfuse_secret_key", None)

    observability.flush()
