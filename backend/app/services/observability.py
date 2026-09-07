"""Self-hosted Langfuse tracing (plan §8) — deliberately optional and
fail-open: the chat pipeline must produce identical answers whether or not
Langfuse is configured, running, or reachable. Every function here is a
harmless no-op if `langfuse_host`/`langfuse_public_key`/`langfuse_secret_key`
aren't all set, or if the client itself fails to initialize — tracing is
observability, not a dependency the user-facing feature should ever break
on.

Never points at a cloud/SaaS host — `langfuse_host` must be explicitly
configured to a self-hosted instance (see
infra/docker-compose.langfuse.yml and docs/CHATBOT_INTEGRATION_PLAN.md §8).
The SDK is OTel-based (spans are batched/exported asynchronously in the
background by design), so a genuinely unreachable host degrades to
"traces silently never arrive," not a blocked or crashed request — this
module's defensive wrapping is for the narrower case of the client itself
failing to construct or a span failing to start.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def _client() -> Any | None:
    settings = get_settings()
    if not (
        settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key
    ):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
    except Exception:
        logger.warning("Langfuse client failed to initialize; tracing disabled.", exc_info=True)
        return None


def is_enabled() -> bool:
    return _client() is not None


@contextmanager
def trace_span(name: str, *, as_type: str = "span", **metadata: Any) -> Iterator[None]:
    """Wraps one pipeline stage (plan §2's guardrail-check -> intent-
    routing -> hybrid-retrieval -> reranking -> generation ->
    faithfulness-check call tree) as one span. Only failures to *start*
    the span are caught here — an exception raised by the code running
    inside the traced block must still propagate normally; only the
    tracing machinery itself is allowed to fail silently."""
    client = _client()
    if client is None:
        yield
        return
    try:
        span_context = client.start_as_current_observation(
            name=name, as_type=as_type, metadata=metadata or None
        )
    except Exception:
        logger.warning(
            "Langfuse span %r failed to start; continuing untraced.", name, exc_info=True
        )
        yield
        return
    with span_context:
        yield


def current_trace_id() -> str | None:
    client = _client()
    if client is None:
        return None
    try:
        result: str | None = client.get_current_trace_id()
        return result
    except Exception:
        return None


def record_feedback_score(*, trace_id: str, is_positive: bool) -> None:
    """Closes the loop described in plan §7.2: an in-app thumbs up/down
    becomes a Langfuse score attached to that message's own trace, so
    flagged conversations are inspectable as evaluation candidates
    alongside the trace that produced them."""
    client = _client()
    if client is None:
        return
    try:
        client.create_score(
            trace_id=trace_id,
            name="user_feedback",
            value="up" if is_positive else "down",
            data_type="CATEGORICAL",
        )
        client.flush()
    except Exception:
        logger.warning(
            "Failed to record Langfuse feedback score for trace %s.", trace_id, exc_info=True
        )


def flush() -> None:
    client = _client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.warning("Langfuse flush failed.", exc_info=True)
