"""SSE reconnection endpoint — single unified API.

Handles both initial state restoration AND Redis stream replay.

Phase 0: Initial state from ThreadStore (if available)
Phase 1: Check Redis for stream data
Phase 2: Catch-up — XRANGE (filtered if ThreadStore sent state, unfiltered otherwise)
Phase 3: Live follow — XREAD BLOCK, unfiltered
"""

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stream_reconnection_demo.agent.segment.routes import run_segment_pipeline
from stream_reconnection_demo.core.events import EventEmitter
from stream_reconnection_demo.core.history import thread_store
from stream_reconnection_demo.core.middleware import _parse_sse_event

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)

# Stale run timeout in seconds
STALE_TIMEOUT = 30

# Fast-forward delays per event type (in seconds) during XRANGE catch-up
FAST_FORWARD_DELAYS: dict[str, float] = {
    "STEP_STARTED": 0.2,
    "STEP_FINISHED": 0.2,
    "ACTIVITY_SNAPSHOT": 0.15,
    "REASONING_START": 0.05,
    "REASONING_MESSAGE_START": 0.0,
    "REASONING_MESSAGE_CONTENT": 0.05,
    "REASONING_MESSAGE_END": 0.0,
    "REASONING_END": 0.05,
    "TOOL_CALL_START": 0.1,
    "TOOL_CALL_ARGS": 0.1,
    "TOOL_CALL_END": 0.1,
    "STATE_DELTA": 0.0,
    "STATE_SNAPSHOT": 0.0,
    "MESSAGES_SNAPSHOT": 0.0,
    "RUN_STARTED": 0.0,
    "RUN_FINISHED": 0.0,
    "CUSTOM": 0.0,
}

# Event types to SKIP during catch-up ONLY when ThreadStore already sent state
# (these would duplicate what ThreadStore provided)
CATCHUP_SKIP_TYPES: frozenset[str] = frozenset({
    "MESSAGES_SNAPSHOT",
    "STATE_SNAPSHOT",
    "STATE_DELTA",
    "TEXT_MESSAGE_START",
    "TEXT_MESSAGE_CONTENT",
    "TEXT_MESSAGE_END",
    "RUN_STARTED",
    "RUN_FINISHED",
})


@router.get("/reconnect/{thread_id}")
async def reconnect_stream(thread_id: str, request: Request):
    """SSE endpoint for reconnecting to an active or completed stream.

    Single unified API that handles:
    - Completed runs: ThreadStore state or full Redis replay
    - Active runs: catch-up from Redis + live follow
    - Server restart: falls back to Redis (ThreadStore empty)
    """
    redis_manager = request.app.state.redis_manager

    async def replay_stream():
        # --- Phase 0: Try ThreadStore for initial state ---
        logger.info(
            "Reconnect: looking up thread %s (known threads: %s)",
            thread_id,
            list(thread_store._threads.keys()),
        )
        thread = thread_store.get_thread(thread_id)
        has_threadstore_state = thread is not None

        synthetic_run_id = str(uuid.uuid4())
        yield emitter.emit_run_started(thread_id, synthetic_run_id)

        if has_threadstore_state:
            logger.info("Reconnect: ThreadStore has thread %s", thread_id)
            if thread["messages"]:
                yield emitter.emit_messages_snapshot(thread["messages"])
            if thread["state"]:
                yield emitter.emit_state_snapshot(thread["state"])
        else:
            logger.info(
                "Reconnect: ThreadStore empty for %s, will try Redis",
                thread_id,
            )

        # --- Phase 1: Check Redis for any stream (active or completed) ---
        run_id = None
        is_active = False
        try:
            run_id = await redis_manager.get_active_run(thread_id)
            if run_id:
                is_active = True
                logger.info(
                    "Reconnect: ACTIVE run %s for %s", run_id, thread_id
                )
            else:
                # No active run — try to find a completed stream
                run_id = await redis_manager.find_stream(thread_id)
                if run_id:
                    logger.info(
                        "Reconnect: COMPLETED stream %s for %s",
                        run_id, thread_id,
                    )
        except Exception:
            logger.warning(
                "Redis unavailable during reconnect for %s", thread_id
            )

        if run_id is None or (has_threadstore_state and not is_active):
            if has_threadstore_state:
                logger.info(
                    "Reconnect: completed run for %s, ThreadStore state sent (skip Redis replay)",
                    thread_id,
                )
                yield emitter.emit_run_finished(thread_id, synthetic_run_id)
                return
            else:
                logger.warning(
                    "Reconnect: no data anywhere for %s", thread_id
                )
                yield emitter.emit_run_error(
                    "Thread not found (no Redis stream, no stored state)"
                )
                return

        # --- Phase 2: Catch-up (XRANGE, non-blocking) ---
        logger.info(
            "Reconnect: active run %s for %s, starting catch-up (filtered=%s)",
            run_id, thread_id, has_threadstore_state,
        )

        last_id = "0"
        stream_ended = False

        try:
            entries = await redis_manager.read_existing(thread_id, run_id)
            logger.info(
                "Reconnect: XRANGE returned %d entries for %s",
                len(entries), thread_id,
            )
        except Exception:
            logger.warning("Redis read_existing failed, skipping catch-up")
            entries = []

        for msg_id, fields in entries:
            event_type = fields.get("type", "")
            last_id = msg_id

            # Check for stream end sentinel
            if event_type == "STREAM_END":
                stream_ended = True
                break
            if event_type == "STREAM_ERROR":
                stream_ended = True
                break

            # Type-based filtering: only skip if ThreadStore already sent state
            if has_threadstore_state and event_type in CATCHUP_SKIP_TYPES:
                continue

            # When replaying without ThreadStore, skip RUN_STARTED/RUN_FINISHED
            # since we already emitted our own synthetic ones
            if not has_threadstore_state and event_type in (
                "RUN_STARTED", "RUN_FINISHED"
            ):
                continue

            # Replay this event
            event_data = fields.get("data", "")
            if event_data:
                yield event_data
                # Fast-forward delay based on event type
                delay = FAST_FORWARD_DELAYS.get(event_type, 0.0)
                if delay > 0:
                    await asyncio.sleep(delay)

        # --- Stale detection ---
        if not stream_ended and is_active and entries:
            try:
                last_ts = await redis_manager.get_last_event_timestamp(
                    thread_id, run_id
                )
                if last_ts is not None:
                    age = time.time() - last_ts
                    if age > STALE_TIMEOUT:
                        logger.warning(
                            "Reconnect: STALE run %s for %s (last event %.0fs ago)",
                            run_id, thread_id, age,
                        )
                        is_active = False
                        stream_ended = True

                        yield emitter.emit_custom(
                            "run_stale",
                            {"reason": "no_heartbeat", "age_seconds": age},
                        )

                        await redis_manager.clear_active_run(thread_id)

                        # Auto-resubmit: find last user query
                        last_query = None
                        thread = thread_store.get_thread(thread_id)
                        if thread and thread["messages"]:
                            for msg in reversed(thread["messages"]):
                                if msg.get("role") == "user":
                                    last_query = msg.get("content", "")
                                    break

                        if last_query:
                            yield emitter.emit_custom(
                                "run_restarted",
                                {"reason": "auto_resubmit"},
                            )

                            new_run_id = str(uuid.uuid4())
                            segment_graph = request.app.state.segment_graph

                            try:
                                await redis_manager.start_run(thread_id, new_run_id)
                                await redis_manager.push_run_history(thread_id, new_run_id)
                            except Exception:
                                logger.warning("Redis start for resubmit failed")

                            from stream_reconnection_demo.core.middleware import RedisStreamMiddleware

                            raw_pipeline = run_segment_pipeline(
                                segment_graph,
                                last_query,
                                thread_id,
                                new_run_id,
                            )

                            persisted_pipeline = RedisStreamMiddleware(
                                redis_manager, thread_id, new_run_id
                            ).apply(raw_pipeline)

                            async for event in persisted_pipeline:
                                yield event
                            return
                        else:
                            logger.warning(
                                "Reconnect: stale run but no user query to resubmit for %s",
                                thread_id,
                            )
            except Exception:
                logger.warning("Stale detection failed for %s", thread_id)

        if stream_ended:
            logger.info(
                "Reconnect: catch-up found STREAM_END for %s, run complete",
                thread_id,
            )
            yield emitter.emit_run_finished(thread_id, synthetic_run_id)
            return

        # Signal catch-up complete before entering live follow
        yield emitter.emit_custom(
            "catchup_complete",
            {"replayed_count": len(entries)},
        )

        # --- Phase 3: Live follow (XREAD BLOCK, unfiltered) ---
        logger.info(
            "Reconnect: switching to live follow for %s from %s",
            thread_id, last_id,
        )

        try:
            async for entry in redis_manager.follow_live(
                thread_id, run_id, last_id
            ):
                event_data = entry["data"]
                if event_data:
                    yield event_data
        except Exception:
            logger.warning("Redis live follow failed for %s", thread_id)

        logger.info("Reconnect: completed for thread %s", thread_id)
        yield emitter.emit_run_finished(thread_id, synthetic_run_id)

    return StreamingResponse(
        replay_stream(),
        media_type=emitter.content_type,
    )
