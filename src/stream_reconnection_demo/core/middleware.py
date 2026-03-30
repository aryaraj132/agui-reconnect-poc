"""Middleware infrastructure for AG-UI event stream processing.

Provides composable async generator wrappers that transform an SSE event
stream.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


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


class LoggingMiddleware:
    """Logs each event type via :func:`logging.info`, yields event unchanged."""

    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        async for event in event_stream:
            parsed = _parse_sse_event(event)
            if parsed is not None:
                event_type = parsed.get("type", "UNKNOWN")
                logger.info("AG-UI event: %s", event_type)
            yield event
