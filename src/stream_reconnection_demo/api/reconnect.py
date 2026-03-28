"""SSE reconnection endpoint for resuming interrupted streams.

When a client reloads the browser mid-stream, this endpoint replays
all events from the Redis stream and follows live for in-progress runs.
"""

import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stream_reconnection_demo.core.events import EventEmitter
from stream_reconnection_demo.core.history import thread_store

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)


@router.get("/reconnect/{thread_id}")
async def reconnect_stream(thread_id: str, request: Request):
    """SSE endpoint for reconnecting to an active or completed stream.

    If a run is active: replays all events from Redis stream and follows live.
    If no active run: returns state from ThreadStore as a synthetic mini-run.
    """
    redis_manager = request.app.state.redis_manager

    async def replay_stream():
        # 1. Look up thread
        thread = thread_store.get_thread(thread_id)
        if thread is None:
            yield emitter.emit_run_error("Thread not found")
            return

        # 2. Check for active run
        run_id = await redis_manager.get_active_run(thread_id)

        if run_id is None:
            # --- NO ACTIVE RUN (completed or never started) ---
            # Emit a synthetic mini-run with current state
            synthetic_run_id = str(uuid.uuid4())
            logger.info(
                "Reconnect: no active run for %s, sending state snapshot",
                thread_id,
            )

            yield emitter.emit_run_started(thread_id, synthetic_run_id)

            if thread["messages"]:
                yield emitter.emit_messages_snapshot(thread["messages"])

            if thread["state"]:
                yield emitter.emit_state_snapshot(thread["state"])

            yield emitter.emit_run_finished(thread_id, synthetic_run_id)
            return

        # --- ACTIVE RUN (in progress) ---
        # Replay all events from Redis stream + follow live
        logger.info(
            "Reconnect: active run %s for %s, replaying from Redis",
            run_id,
            thread_id,
        )

        event_count = 0
        async for entry in redis_manager.read_events(thread_id, run_id):
            event_data = entry["data"]
            if event_data:
                yield event_data
                event_count += 1

        logger.info(
            "Reconnect: replayed %d events for thread %s run %s",
            event_count,
            thread_id,
            run_id,
        )

    return StreamingResponse(
        replay_stream(),
        media_type=emitter.content_type,
    )
