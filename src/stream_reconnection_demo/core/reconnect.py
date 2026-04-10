"""Common checkpointer-based reconnection handler for AG-UI agents.

Provides a shared 3-tier connect pattern used by agents that rely on
LangGraph's checkpointer for state persistence:

1. **Active run** — synthetic catch-up from checkpointer + live Pub/Sub
2. **Completed run** — full catch-up from checkpointer
3. **No state** — empty RUN_STARTED + RUN_FINISHED
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from fastapi.responses import StreamingResponse

from stream_reconnection_demo.core.events import EventEmitter
from stream_reconnection_demo.core.pubsub import PubSubManager

logger = logging.getLogger(__name__)
emitter = EventEmitter()


def extract_step_name_from_sse(event_data: str) -> str | None:
    """Extract the step name from a STEP_STARTED SSE event string."""
    for line in event_data.split("\n"):
        if line.startswith("data:"):
            json_str = line[5:].lstrip()
            try:
                payload = json.loads(json_str)
                return payload.get("stepName") or payload.get("step_name")
            except (ValueError, TypeError):
                pass
    return None


@dataclass
class ReconnectConfig:
    """Agent-specific configuration for checkpointer-based reconnection.

    Parameters
    ----------
    node_meta:
        Mapping of node_name → metadata dict. Must include an ``"index"``
        key (int) used for deduplication during active-run catch-up.
    state_snapshot_key:
        The key in checkpointer state to extract for the final
        STATE_SNAPSHOT (e.g. ``"template"``, ``"segment"``).
    emit_catchup:
        Async generator ``(state, thread_id, run_id, next_nodes) → SSE str``.
        Emits synthetic AG-UI events from checkpointer state for catch-up.
        Must emit RUN_STARTED as its first event.
    get_completed_count:
        Callable ``(state, next_nodes) → int``. Returns the number of
        completed nodes, used to determine the dedup boundary.
    serialize_snapshot:
        Optional callable to serialize a state value before emitting it
        as a STATE_SNAPSHOT (e.g. ``obj.model_dump()``). Defaults to
        identity (pass-through).
    """

    node_meta: dict[str, dict]
    state_snapshot_key: str
    emit_catchup: Callable[[dict, str, str, tuple], AsyncIterator[str]]
    get_completed_count: Callable[[dict, tuple], int]
    serialize_snapshot: Callable[[Any], Any] = lambda x: x


async def handle_checkpointer_connect(
    pubsub: PubSubManager,
    graph: Any,
    thread_id: str,
    run_id: str,
    config: ReconnectConfig,
) -> StreamingResponse:
    """Handle a connect/reconnect request using checkpointer state.

    Implements the 3-tier fallback pattern shared by all checkpointer-based
    agents. Agent-specific catch-up content is provided via ``config``.
    """

    # Tier 1: Active run — catch-up + live events
    active_run_id = None
    try:
        active_run_id = await pubsub.get_active_run(thread_id)
    except Exception:
        logger.warning("Failed to check active run for thread %s", thread_id)

    if active_run_id:
        logger.info(
            "Connect: active run %s, catching up from checkpointer",
            active_run_id,
        )

        async def reconnect_stream():
            async with pubsub.open_subscription(
                thread_id, active_run_id
            ) as live_events:
                # Read checkpointer state for synthetic catch-up
                catchup_node_index = -1
                try:
                    checkpoint_state = await graph.aget_state(
                        {"configurable": {"thread_id": thread_id}}
                    )
                except Exception:
                    checkpoint_state = None

                # Emit synthetic catch-up for completed nodes
                if checkpoint_state and checkpoint_state.values:
                    next_nodes = getattr(checkpoint_state, "next", ())
                    completed_count = config.get_completed_count(
                        checkpoint_state.values, next_nodes
                    )
                    catchup_node_index = completed_count - 1

                    async for event in config.emit_catchup(
                        checkpoint_state.values, thread_id, run_id, next_nodes
                    ):
                        yield event

                # Forward live events, skipping nodes already covered
                past_catchup = catchup_node_index < 0

                async for event_data in live_events:
                    if not past_catchup:
                        if "STEP_STARTED" in event_data:
                            step_name = extract_step_name_from_sse(event_data)
                            if step_name and step_name in config.node_meta:
                                if (
                                    config.node_meta[step_name]["index"]
                                    > catchup_node_index
                                ):
                                    past_catchup = True
                        elif (
                            "TEXT_MESSAGE_START" in event_data
                            or "RUN_FINISHED" in event_data
                        ):
                            past_catchup = True

                        if not past_catchup:
                            continue

                    yield event_data

                # Safety: if stream ended without getting past catch-up,
                # read final state and emit RUN_FINISHED
                if not past_catchup:
                    try:
                        final_state = await graph.aget_state(
                            {"configurable": {"thread_id": thread_id}}
                        )
                        if final_state and final_state.values:
                            snapshot = final_state.values.get(
                                config.state_snapshot_key
                            )
                            if snapshot is not None:
                                serialized = config.serialize_snapshot(snapshot)
                                yield emitter.emit_state_snapshot(serialized)
                    except Exception:
                        pass
                    yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            reconnect_stream(), media_type=emitter.content_type
        )

    # Tier 2: No active run — check checkpointer for completed state
    try:
        checkpoint_state = await graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        checkpoint_state = None

    if checkpoint_state and checkpoint_state.values:
        logger.info(
            "Connect: completed state from checkpointer for thread %s",
            thread_id,
        )

        async def completed_stream():
            async for event in config.emit_catchup(
                checkpoint_state.values,
                thread_id,
                run_id,
                getattr(checkpoint_state, "next", ()),
            ):
                yield event
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            completed_stream(), media_type=emitter.content_type
        )

    # Tier 3: Nothing found
    logger.info("Connect: no state for thread %s", thread_id)

    async def empty_stream():
        yield emitter.emit_run_started(thread_id, run_id)
        yield emitter.emit_run_finished(thread_id, run_id)

    return StreamingResponse(
        empty_stream(), media_type=emitter.content_type
    )
