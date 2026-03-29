"""Redis Streams manager for AG-UI event persistence and replay.

Stores every SSE event in a Redis Stream keyed by ``stream:{thread_id}:{run_id}``.
Tracks active runs via ``active_run:{thread_id}`` keys.
Supports replay from any point and live following via XREAD BLOCK.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from stream_reconnection_demo.core.middleware import _parse_sse_event

logger = logging.getLogger(__name__)

# Stream entry TTL (seconds) — auto-cleanup after 1 hour
STREAM_TTL = 3600

# Sentinel event types
STREAM_END = "STREAM_END"
STREAM_ERROR = "STREAM_ERROR"


class RedisStreamManager:
    """Manages Redis Streams for AG-UI event persistence and replay."""

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis = aioredis.from_url(
            redis_url, decode_responses=True, encoding="utf-8"
        )

    def _stream_key(self, thread_id: str, run_id: str) -> str:
        return f"stream:{thread_id}:{run_id}"

    def _active_key(self, thread_id: str) -> str:
        return f"active_run:{thread_id}"

    async def start_run(self, thread_id: str, run_id: str) -> None:
        """Register an active run for a thread."""
        await self._redis.set(
            self._active_key(thread_id), run_id, ex=STREAM_TTL
        )
        logger.info("Started run %s for thread %s", run_id, thread_id)

    async def write_event(
        self, thread_id: str, run_id: str, event_sse: str
    ) -> str:
        """Write an SSE event to the Redis stream.

        Returns the Redis stream message ID.
        """
        key = self._stream_key(thread_id, run_id)

        # Extract event type from SSE data
        parsed = _parse_sse_event(event_sse)
        event_type = parsed.get("type", "UNKNOWN") if parsed else "UNKNOWN"

        msg_id = await self._redis.xadd(
            key,
            {
                "type": event_type,
                "data": event_sse,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        return msg_id

    async def mark_complete(self, thread_id: str, run_id: str) -> None:
        """Write end sentinel, remove active key, set TTL on stream."""
        key = self._stream_key(thread_id, run_id)
        await self._redis.xadd(
            key,
            {
                "type": STREAM_END,
                "data": "",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self._redis.delete(self._active_key(thread_id))
        await self._redis.expire(key, STREAM_TTL)
        logger.info("Completed run %s for thread %s", run_id, thread_id)

    async def mark_error(
        self, thread_id: str, run_id: str, error: str
    ) -> None:
        """Write error sentinel, remove active key, set TTL."""
        key = self._stream_key(thread_id, run_id)
        await self._redis.xadd(
            key,
            {
                "type": STREAM_ERROR,
                "data": error,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self._redis.delete(self._active_key(thread_id))
        await self._redis.expire(key, STREAM_TTL)
        logger.info("Error in run %s for thread %s: %s", run_id, thread_id, error)

    async def read_existing(
        self, thread_id: str, run_id: str
    ) -> list[tuple[str, dict[str, str]]]:
        """XRANGE — return all existing entries (non-blocking).

        Returns list of (message_id, fields_dict) tuples.
        """
        key = self._stream_key(thread_id, run_id)
        entries = await self._redis.xrange(key)
        return entries  # list of (msg_id, {type, data, ts})

    async def follow_live(
        self,
        thread_id: str,
        run_id: str,
        last_id: str = "0",
    ) -> AsyncIterator[dict[str, Any]]:
        """XREAD BLOCK — yield new entries until STREAM_END.

        Starts reading from after ``last_id``. Blocks up to 2 seconds
        per read cycle. Stops when STREAM_END or STREAM_ERROR sentinel
        is encountered, or when the run is no longer active.
        """
        key = self._stream_key(thread_id, run_id)

        while True:
            entries = await self._redis.xread(
                {key: last_id}, block=2000, count=50
            )

            if entries:
                for _stream_name, messages in entries:
                    for msg_id, fields in messages:
                        last_id = msg_id
                        event_type = fields.get("type", "")

                        if event_type in (STREAM_END, STREAM_ERROR):
                            return

                        yield {
                            "id": msg_id,
                            "type": event_type,
                            "data": fields.get("data", ""),
                            "ts": fields.get("ts", ""),
                        }
            else:
                # No new entries within timeout — check if run is still active
                active = await self.get_active_run(thread_id)
                if active != run_id:
                    # Do one final non-blocking read
                    remaining = await self._redis.xread(
                        {key: last_id}, count=100
                    )
                    if remaining:
                        for _stream_name, messages in remaining:
                            for msg_id, fields in messages:
                                event_type = fields.get("type", "")
                                if event_type in (STREAM_END, STREAM_ERROR):
                                    return
                                yield {
                                    "id": msg_id,
                                    "type": event_type,
                                    "data": fields.get("data", ""),
                                    "ts": fields.get("ts", ""),
                                }
                    return

    async def stream_exists(self, thread_id: str, run_id: str) -> bool:
        """Check if a Redis stream exists for the given thread and run."""
        key = self._stream_key(thread_id, run_id)
        return await self._redis.exists(key) > 0

    async def get_active_run(self, thread_id: str) -> str | None:
        """Return the active run_id for a thread, or None."""
        return await self._redis.get(self._active_key(thread_id))

    async def get_last_event_timestamp(self, thread_id: str, run_id: str) -> float | None:
        """Return the Unix timestamp of the most recent event in the stream.

        Uses XREVRANGE with COUNT 1 to efficiently get the last entry.
        Returns None if the stream is empty or doesn't exist.
        """
        key = self._stream_key(thread_id, run_id)
        entries = await self._redis.xrevrange(key, count=1)
        if not entries:
            return None
        _msg_id, fields = entries[0]
        ts_str = fields.get("ts", "")
        if ts_str:
            try:
                dt = datetime.fromisoformat(ts_str)
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        # Fallback: parse the Redis message ID (millisecond timestamp)
        msg_id_str = entries[0][0]
        try:
            return int(msg_id_str.split("-")[0]) / 1000.0
        except (ValueError, IndexError):
            return None

    async def clear_active_run(self, thread_id: str) -> None:
        """Delete the active_run key for a thread.

        Used during stale run cleanup to allow new runs to start.
        """
        await self._redis.delete(self._active_key(thread_id))
        logger.info("Cleared active_run for thread %s", thread_id)

    async def push_run_history(self, thread_id: str, run_id: str) -> None:
        """Append a run_id to the thread's run history list."""
        key = f"run_history:{thread_id}"
        await self._redis.rpush(key, run_id)
        await self._redis.expire(key, STREAM_TTL)
        logger.info("Pushed run %s to history for thread %s", run_id, thread_id)

    async def get_run_history(self, thread_id: str) -> list[str]:
        """Return all run_ids for a thread in chronological order."""
        key = f"run_history:{thread_id}"
        return await self._redis.lrange(key, 0, -1)

    async def find_stream(self, thread_id: str) -> str | None:
        """Find any stream (active or completed) for a thread.

        Checks active_run key first, then scans for stream:thread_id:* keys.
        Returns the run_id if found, None otherwise.
        """
        # Check active run first
        active = await self.get_active_run(thread_id)
        if active:
            return active

        # Scan for completed streams (key pattern: stream:{thread_id}:*)
        pattern = f"stream:{thread_id}:*"
        async for key in self._redis.scan_iter(match=pattern, count=10):
            # Extract run_id from key: "stream:{thread_id}:{run_id}"
            parts = key.split(":", 2)
            if len(parts) == 3:
                return parts[2]
        return None

    async def read_events(
        self,
        thread_id: str,
        run_id: str,
        last_id: str = "0",
    ) -> AsyncIterator[dict[str, Any]]:
        """Read events from a Redis stream, following live if active.

        Yields dicts with keys: ``type``, ``data``, ``ts``, ``id``.
        Stops when STREAM_END or STREAM_ERROR sentinel is encountered,
        or when the run is no longer active and no new events arrive.
        """
        key = self._stream_key(thread_id, run_id)

        while True:
            # Use blocking read with 2-second timeout
            entries = await self._redis.xread(
                {key: last_id}, block=2000, count=50
            )

            if entries:
                for _stream_name, messages in entries:
                    for msg_id, fields in messages:
                        last_id = msg_id
                        event_type = fields.get("type", "")

                        if event_type == STREAM_END:
                            return
                        if event_type == STREAM_ERROR:
                            return

                        yield {
                            "id": msg_id,
                            "type": event_type,
                            "data": fields.get("data", ""),
                            "ts": fields.get("ts", ""),
                        }
            else:
                # No new entries within timeout — check if run is still active
                active = await self.get_active_run(thread_id)
                if active != run_id:
                    # Run completed or errored between XREAD calls.
                    # Do one final non-blocking read to catch any remaining entries.
                    remaining = await self._redis.xread(
                        {key: last_id}, count=100
                    )
                    if remaining:
                        for _stream_name, messages in remaining:
                            for msg_id, fields in messages:
                                event_type = fields.get("type", "")
                                if event_type in (STREAM_END, STREAM_ERROR):
                                    return
                                yield {
                                    "id": msg_id,
                                    "type": event_type,
                                    "data": fields.get("data", ""),
                                    "ts": fields.get("ts", ""),
                                }
                    return

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self._redis.aclose()
