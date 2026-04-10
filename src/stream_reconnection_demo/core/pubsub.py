"""Pub/Sub managers for AG-UI event streaming and persistence.

Provides two implementations behind a common ``PubSubManager`` protocol:

- ``RedisPubSubManager`` — uses Redis Pub/Sub for real-time fan-out and
  Redis Lists for ordered event persistence (supports reconnection).
- ``InMemoryPubSubManager`` — pure-Python fallback that keeps events in
  memory.  Live streaming works, but reconnection after a page reload
  will lose events because nothing is persisted.

Redis key layout (only relevant for ``RedisPubSubManager``)
-----------------------------------------------------------
- ``agent:{thread_id}:{run_id}``       — Pub/Sub channel (live events)
- ``events:{thread_id}:{run_id}``      — Redis List   (persisted events)
- ``active_run:{thread_id}``           — String        (current run_id)
- ``run_status:{thread_id}:{run_id}``  — String        (running | completed | error)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Key TTL in seconds — auto-cleanup after 1 hour
KEY_TTL = 3600

# Sentinel strings published on the Pub/Sub channel to signal end-of-stream
STREAM_END = "STREAM_END"
STREAM_ERROR = "STREAM_ERROR"


# ---------------------------------------------------------------------------
# Protocol — shared interface for Redis and in-memory implementations
# ---------------------------------------------------------------------------


@runtime_checkable
class PubSubManager(Protocol):
    """Common interface implemented by both Redis and in-memory backends."""

    async def start_run(self, thread_id: str, run_id: str) -> None: ...
    async def complete_run(self, thread_id: str, run_id: str) -> None: ...
    async def error_run(self, thread_id: str, run_id: str, error: str) -> None: ...
    async def publish_event(self, thread_id: str, run_id: str, event_data: str) -> int: ...
    async def get_active_run(self, thread_id: str) -> str | None: ...
    async def get_run_status(self, thread_id: str, run_id: str) -> str | None: ...
    async def read_events(self, thread_id: str, run_id: str) -> list[str]: ...
    async def get_event_count(self, thread_id: str, run_id: str) -> int: ...
    async def subscribe_and_stream(self, thread_id: str, run_id: str, last_seq: int = 0) -> AsyncIterator[str]: ...
    async def catch_up_and_follow(self, thread_id: str, run_id: str) -> AsyncIterator[str]: ...
    async def publish_event_pubsub_only(self, thread_id: str, run_id: str, event_data: str, seq: int) -> None: ...
    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# In-memory implementation (fallback when Redis is unavailable)
# ---------------------------------------------------------------------------


class InMemoryPubSubManager:
    """Pure-Python Pub/Sub manager that stores everything in memory.

    Provides the same interface as ``RedisPubSubManager`` so the rest of
    the application can work without Redis.  Reconnection / catch-up on
    page reload will *not* work because events are lost once consumed, but
    normal SSE streaming works fine.
    """

    def __init__(self) -> None:
        # run lifecycle
        self._active_runs: dict[str, str] = {}                    # thread_id -> run_id
        self._run_statuses: dict[str, str] = {}                   # "thread:run" -> status
        # event persistence
        self._events: dict[str, list[str]] = {}                   # "thread:run" -> [event_data, ...]
        # pub/sub fan-out: channel -> set of asyncio.Queue
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _key(thread_id: str, run_id: str) -> str:
        return f"{thread_id}:{run_id}"

    def _publish_to_channel(self, key: str, data: str) -> None:
        for q in self._subscribers.get(key, set()):
            q.put_nowait(data)

    # -- run lifecycle ------------------------------------------------------

    async def start_run(self, thread_id: str, run_id: str) -> None:
        self._active_runs[thread_id] = run_id
        self._run_statuses[self._key(thread_id, run_id)] = "running"
        logger.info("Started run %s for thread %s (in-memory)", run_id, thread_id)

    async def complete_run(self, thread_id: str, run_id: str) -> None:
        key = self._key(thread_id, run_id)
        self._run_statuses[key] = "completed"
        self._active_runs.pop(thread_id, None)
        self._publish_to_channel(key, STREAM_END)
        logger.info("Completed run %s for thread %s (in-memory)", run_id, thread_id)

    async def error_run(self, thread_id: str, run_id: str, error: str) -> None:
        key = self._key(thread_id, run_id)
        self._run_statuses[key] = "error"
        self._active_runs.pop(thread_id, None)
        self._publish_to_channel(key, STREAM_ERROR)
        logger.info("Error in run %s for thread %s: %s (in-memory)", run_id, thread_id, error)

    # -- publish + persist --------------------------------------------------

    async def publish_event(self, thread_id: str, run_id: str, event_data: str) -> int:
        key = self._key(thread_id, run_id)
        events = self._events.setdefault(key, [])
        events.append(event_data)
        seq = len(events)
        envelope = json.dumps({"seq": seq, "event": event_data})
        self._publish_to_channel(key, envelope)
        return seq

    # -- query helpers ------------------------------------------------------

    async def get_active_run(self, thread_id: str) -> str | None:
        return self._active_runs.get(thread_id)

    async def get_run_status(self, thread_id: str, run_id: str) -> str | None:
        return self._run_statuses.get(self._key(thread_id, run_id))

    # -- catch-up (list reads) ---------------------------------------------

    async def read_events(self, thread_id: str, run_id: str) -> list[str]:
        return list(self._events.get(self._key(thread_id, run_id), []))

    async def get_event_count(self, thread_id: str, run_id: str) -> int:
        return len(self._events.get(self._key(thread_id, run_id), []))

    # -- subscribe + deduplicate -------------------------------------------

    async def subscribe_and_stream(
        self,
        thread_id: str,
        run_id: str,
        last_seq: int = 0,
    ) -> AsyncIterator[str]:
        key = self._key(thread_id, run_id)
        q: asyncio.Queue[str] = asyncio.Queue()
        subs = self._subscribers.setdefault(key, set())
        subs.add(q)

        try:
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    status = await self.get_run_status(thread_id, run_id)
                    if status in ("completed", "error", None):
                        return
                    continue

                if raw in (STREAM_END, STREAM_ERROR):
                    return

                try:
                    envelope = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                seq = envelope.get("seq", 0)
                if seq <= last_seq:
                    continue

                last_seq = seq
                yield envelope["event"]
        finally:
            subs.discard(q)

    async def catch_up_and_follow(
        self,
        thread_id: str,
        run_id: str,
    ) -> AsyncIterator[str]:
        key = self._key(thread_id, run_id)
        q: asyncio.Queue[str] = asyncio.Queue()
        subs = self._subscribers.setdefault(key, set())
        subs.add(q)

        try:
            # Phase 1: catch-up from stored events
            events = self._events.get(key, [])
            seen_seq = 0
            for event_data in events:
                seen_seq += 1
                yield event_data

            status = await self.get_run_status(thread_id, run_id)
            if status in ("completed", "error"):
                return

            # Phase 2: live follow
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    status = await self.get_run_status(thread_id, run_id)
                    if status in ("completed", "error", None):
                        remaining = self._events.get(key, [])[seen_seq:]
                        for event_data in remaining:
                            seen_seq += 1
                            yield event_data
                        return
                    continue

                if raw in (STREAM_END, STREAM_ERROR):
                    remaining = self._events.get(key, [])[seen_seq:]
                    for event_data in remaining:
                        seen_seq += 1
                        yield event_data
                    return

                try:
                    envelope = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                seq = envelope.get("seq", 0)
                if seq <= seen_seq:
                    continue

                seen_seq = seq
                yield envelope["event"]
        finally:
            subs.discard(q)

    # -- pub/sub-only publishing -------------------------------------------

    async def publish_event_pubsub_only(
        self, thread_id: str, run_id: str, event_data: str, seq: int
    ) -> None:
        key = self._key(thread_id, run_id)
        envelope = json.dumps({"seq": seq, "event": event_data})
        self._publish_to_channel(key, envelope)

    # -- cleanup ------------------------------------------------------------

    async def close(self) -> None:
        self._active_runs.clear()
        self._run_statuses.clear()
        self._events.clear()
        self._subscribers.clear()


# ---------------------------------------------------------------------------
# Redis implementation
# ---------------------------------------------------------------------------


class RedisPubSubManager:
    """Manages Redis Pub/Sub + Lists for AG-UI event streaming."""

    def __init__(self, redis_url: str = "redis://localhost:63791") -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            redis_url, decode_responses=True, encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _channel_key(thread_id: str, run_id: str) -> str:
        """Pub/Sub channel name."""
        return f"agent:{thread_id}:{run_id}"

    @staticmethod
    def _events_key(thread_id: str, run_id: str) -> str:
        """Redis List key for persisted events."""
        return f"events:{thread_id}:{run_id}"

    @staticmethod
    def _active_run_key(thread_id: str) -> str:
        """String key holding the active run_id for a thread."""
        return f"active_run:{thread_id}"

    @staticmethod
    def _run_status_key(thread_id: str, run_id: str) -> str:
        """String key holding the run status (running | completed | error)."""
        return f"run_status:{thread_id}:{run_id}"

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    async def start_run(self, thread_id: str, run_id: str) -> None:
        """Register a new active run for *thread_id*.

        Sets the ``active_run`` pointer and marks the run status as
        ``running``.  Both keys expire after ``KEY_TTL`` seconds.
        """
        pipe = self._redis.pipeline()
        pipe.set(self._active_run_key(thread_id), run_id, ex=KEY_TTL)
        pipe.set(self._run_status_key(thread_id, run_id), "running", ex=KEY_TTL)
        await pipe.execute()
        logger.info("Started run %s for thread %s", run_id, thread_id)

    async def complete_run(self, thread_id: str, run_id: str) -> None:
        """Mark *run_id* as completed.

        Updates status, removes the active-run pointer, and publishes the
        ``STREAM_END`` sentinel so live subscribers terminate cleanly.
        """
        pipe = self._redis.pipeline()
        pipe.set(
            self._run_status_key(thread_id, run_id), "completed", ex=KEY_TTL
        )
        pipe.delete(self._active_run_key(thread_id))
        await pipe.execute()

        # Publish sentinel *after* state is consistent
        await self._redis.publish(
            self._channel_key(thread_id, run_id), STREAM_END
        )
        logger.info("Completed run %s for thread %s", run_id, thread_id)

    async def error_run(
        self, thread_id: str, run_id: str, error: str
    ) -> None:
        """Mark *run_id* as errored.

        Updates status, removes the active-run pointer, and publishes the
        ``STREAM_ERROR`` sentinel.
        """
        pipe = self._redis.pipeline()
        pipe.set(
            self._run_status_key(thread_id, run_id), "error", ex=KEY_TTL
        )
        pipe.delete(self._active_run_key(thread_id))
        await pipe.execute()

        await self._redis.publish(
            self._channel_key(thread_id, run_id), STREAM_ERROR
        )
        logger.info(
            "Error in run %s for thread %s: %s", run_id, thread_id, error
        )

    # ------------------------------------------------------------------
    # Publish + persist
    # ------------------------------------------------------------------

    async def publish_event(
        self, thread_id: str, run_id: str, event_data: str
    ) -> int:
        """Persist *event_data* in the List and fan it out via Pub/Sub.

        Returns the 1-based sequence number of the event (i.e. the new
        length of the List after RPUSH).
        """
        events_key = self._events_key(thread_id, run_id)

        # RPUSH returns the new length — that *is* the 1-based seq number
        seq: int = await self._redis.rpush(events_key, event_data)

        # Ensure the list has a TTL (idempotent on subsequent calls)
        await self._redis.expire(events_key, KEY_TTL)

        # Fan-out: include the seq so subscribers can deduplicate
        envelope = json.dumps({"seq": seq, "event": event_data})
        await self._redis.publish(
            self._channel_key(thread_id, run_id), envelope
        )

        return seq

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_active_run(self, thread_id: str) -> str | None:
        """Return the active run_id for *thread_id*, or ``None``."""
        return await self._redis.get(self._active_run_key(thread_id))

    async def get_run_status(
        self, thread_id: str, run_id: str
    ) -> str | None:
        """Return the run status string, or ``None`` if unknown."""
        return await self._redis.get(self._run_status_key(thread_id, run_id))

    # ------------------------------------------------------------------
    # Catch-up (List reads)
    # ------------------------------------------------------------------

    async def read_events(
        self, thread_id: str, run_id: str
    ) -> list[str]:
        """Return all persisted events for the run (LRANGE 0 -1)."""
        return await self._redis.lrange(
            self._events_key(thread_id, run_id), 0, -1
        )

    async def get_event_count(
        self, thread_id: str, run_id: str
    ) -> int:
        """Return the number of persisted events (LLEN)."""
        return await self._redis.llen(self._events_key(thread_id, run_id))

    # ------------------------------------------------------------------
    # Subscribe + deduplicate
    # ------------------------------------------------------------------

    async def subscribe_and_stream(
        self,
        thread_id: str,
        run_id: str,
        last_seq: int = 0,
    ) -> AsyncIterator[str]:
        """Subscribe to live events and yield those with seq > *last_seq*.

        Stops when a ``STREAM_END`` or ``STREAM_ERROR`` sentinel is
        received.  If the Pub/Sub read times out (5 s), the run status is
        checked — if no longer ``running`` the iterator terminates.
        """
        channel_name = self._channel_key(thread_id, run_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel_name)

        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=5.0
                )

                if msg is None:
                    # Timeout — check if the run is still alive
                    status = await self.get_run_status(thread_id, run_id)
                    if status in ("completed", "error", None):
                        return
                    continue

                if msg["type"] != "message":
                    continue

                raw: str = msg["data"]

                # Sentinel check (plain strings, not JSON)
                if raw in (STREAM_END, STREAM_ERROR):
                    return

                # Normal event envelope: {"seq": N, "event": "..."}
                try:
                    envelope = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                seq = envelope.get("seq", 0)
                if seq <= last_seq:
                    continue

                last_seq = seq
                yield envelope["event"]
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()

    async def catch_up_and_follow(
        self,
        thread_id: str,
        run_id: str,
    ) -> AsyncIterator[str]:
        """Yield all events — historical then live — without gaps.

        **Algorithm (race-condition safe):**

        1. Subscribe to the Pub/Sub channel *first* so any events published
           while we read the List are buffered in the subscription.
        2. LRANGE the full List to get persisted events; yield them and
           record the highest seq seen.
        3. Switch to the Pub/Sub subscription, deduplicating by seq.
        4. Stop on sentinels or terminal run status.
        """
        channel_name = self._channel_key(thread_id, run_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel_name)

        try:
            # -- Phase 1: catch-up from List --------------------------------
            events = await self.read_events(thread_id, run_id)
            seen_seq = 0
            for event_data in events:
                seen_seq += 1
                yield event_data

            # If the run is already done and we have all events, stop early.
            status = await self.get_run_status(thread_id, run_id)
            if status in ("completed", "error"):
                # Drain any remaining Pub/Sub messages (non-blocking) to
                # avoid leaving unread data in the subscription buffer.
                return

            # -- Phase 2: live follow via Pub/Sub ---------------------------
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=5.0
                )

                if msg is None:
                    status = await self.get_run_status(thread_id, run_id)
                    if status in ("completed", "error", None):
                        # One final drain: yield any events that arrived
                        # between the status check and now.
                        remaining = await self._redis.lrange(
                            self._events_key(thread_id, run_id),
                            seen_seq,
                            -1,
                        )
                        for event_data in remaining:
                            seen_seq += 1
                            yield event_data
                        return
                    continue

                if msg["type"] != "message":
                    continue

                raw: str = msg["data"]

                if raw in (STREAM_END, STREAM_ERROR):
                    # Drain any events that might have been RPUSHed right
                    # before the sentinel was published.
                    remaining = await self._redis.lrange(
                        self._events_key(thread_id, run_id),
                        seen_seq,
                        -1,
                    )
                    for event_data in remaining:
                        seen_seq += 1
                        yield event_data
                    return

                try:
                    envelope = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                seq = envelope.get("seq", 0)
                if seq <= seen_seq:
                    # Already yielded during catch-up — skip
                    continue

                seen_seq = seq
                yield envelope["event"]
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()

    # ------------------------------------------------------------------
    # Pub/Sub-only publishing (no List persistence)
    # ------------------------------------------------------------------

    async def publish_event_pubsub_only(
        self, thread_id: str, run_id: str, event_data: str, seq: int
    ) -> None:
        """Publish *event_data* to the Pub/Sub channel only (no List).

        Used by stateful agents where catch-up relies on checkpointer
        state instead of event replay from the Redis List.
        """
        envelope = json.dumps({"seq": seq, "event": event_data})
        await self._redis.publish(
            self._channel_key(thread_id, run_id), envelope
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self._redis.aclose()
