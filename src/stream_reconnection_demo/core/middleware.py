"""Middleware infrastructure for AG-UI event stream processing.

Provides composable async generator wrappers that transform an SSE event
stream.  Middleware is applied innermost-first::

    LoggingMiddleware().apply(
        CapabilityFilterMiddleware(...).apply(
            HistoryMiddleware(...).apply(raw_stream)
        )
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifecycle event types that must never be filtered
# ---------------------------------------------------------------------------

LIFECYCLE_TYPES: frozenset[str] = frozenset(
    {"RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"}
)


# ---------------------------------------------------------------------------
# SSE parsing helper
# ---------------------------------------------------------------------------


def _parse_sse_event(sse_str: str) -> dict[str, Any] | None:
    """Extract the JSON payload from an SSE-formatted string.

    Expected format: ``data: {json}\\n\\n``.  Returns ``None`` when the
    string cannot be parsed (e.g. keep-alive comments).
    """
    line = sse_str.strip()
    if not line.startswith("data: "):
        return None
    json_str = line[len("data: "):]
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# LoggingMiddleware
# ---------------------------------------------------------------------------


class LoggingMiddleware:
    """Logs each event type via :func:`logging.info`, yields event unchanged."""

    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        async for event in event_stream:
            parsed = _parse_sse_event(event)
            if parsed is not None:
                event_type = parsed.get("type", "UNKNOWN")
                logger.info("AG-UI event: %s", event_type)
            yield event


# ---------------------------------------------------------------------------
# CapabilityFilterMiddleware
# ---------------------------------------------------------------------------


class CapabilityFilterMiddleware:
    """Filters events to only allowed types.  Lifecycle events always pass."""

    def __init__(self, allowed_types: set[str]) -> None:
        self._allowed_types: set[str] = set(allowed_types) | LIFECYCLE_TYPES

    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        async for event in event_stream:
            parsed = _parse_sse_event(event)
            if parsed is None:
                # Not a parseable event — pass through (e.g. keep-alive)
                yield event
                continue
            event_type = parsed.get("type", "")
            if event_type in self._allowed_types:
                yield event


# ---------------------------------------------------------------------------
# HistoryMiddleware
# ---------------------------------------------------------------------------


class HistoryMiddleware:
    """Stores each event in a store for serialization/history."""

    def __init__(self, store: Any, thread_id: str) -> None:
        self._store = store
        self._thread_id = thread_id

    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        async for event in event_stream:
            parsed = _parse_sse_event(event)
            if parsed is not None:
                self._store.add_event(self._thread_id, parsed)
            yield event


# ---------------------------------------------------------------------------
# RedisStreamMiddleware
# ---------------------------------------------------------------------------


class RedisStreamMiddleware:
    """Writes every SSE event to a Redis Stream before yielding it.

    This ensures no events are lost if the client disconnects mid-stream.
    The Redis stream can be replayed via the reconnect endpoint.
    """

    def __init__(self, redis_manager: Any, thread_id: str, run_id: str) -> None:
        self._redis = redis_manager
        self._thread_id = thread_id
        self._run_id = run_id

    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        try:
            async for event in event_stream:
                try:
                    await self._redis.write_event(
                        self._thread_id, self._run_id, event
                    )
                except Exception:
                    logger.warning("Redis write_event failed, skipping persistence")
                yield event
            try:
                await self._redis.mark_complete(self._thread_id, self._run_id)
            except Exception:
                logger.warning("Redis mark_complete failed")
        except Exception:
            try:
                await self._redis.mark_error(
                    self._thread_id, self._run_id, "Stream error"
                )
            except Exception:
                logger.warning("Redis mark_error failed")
            raise
