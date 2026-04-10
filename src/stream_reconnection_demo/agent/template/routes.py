"""Template agent endpoint — ag-ui-langgraph + Redis Pub/Sub.

Uses LangGraphAgent for automatic AG-UI event generation.
Checkpointer is the single source of truth for catch-up.
Redis Pub/Sub for live event streaming only (no List).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from ag_ui.core import RunAgentInput, UserMessage
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stream_reconnection_demo.core.event_adapter import EventAdapter
from stream_reconnection_demo.core.events import (
    EventEmitter,
    extract_user_query,
    get_field,
)
from stream_reconnection_demo.core.pubsub import STREAM_END, STREAM_ERROR

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)


@router.post("/template")
async def handle_template(request: Request):
    body = await request.json()

    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    messages = body.get("messages", [])
    query = extract_user_query(messages)
    frontend_state = body.get("state")

    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    template_graph = request.app.state.template_graph
    template_agent = request.app.state.template_agent
    pubsub = request.app.state.pubsub

    logger.info(
        "Template request: thread=%s type=%s query=%s",
        thread_id,
        request_type,
        query[:50] if query else "(empty)",
    )

    if request_type == "connect":
        return await _handle_connect(pubsub, template_graph, thread_id, run_id)

    return await _handle_chat(
        pubsub,
        template_graph,
        template_agent,
        thread_id,
        run_id,
        query,
        frontend_state,
    )


@router.get("/template/state/{thread_id}")
async def get_template_state(thread_id: str, request: Request):
    """Return current template state from checkpointer for a given thread."""
    template_graph = request.app.state.template_graph
    try:
        checkpoint_state = await template_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if checkpoint_state and checkpoint_state.values:
            template = checkpoint_state.values.get("template")
            if template:
                return {"template": template}
    except Exception:
        logger.warning("Failed to read state for thread %s", thread_id)
    return {"template": None}


async def _handle_chat(
    pubsub,
    template_graph,
    template_agent,
    thread_id: str,
    run_id: str,
    query: str,
    frontend_state: dict | None,
):
    """Handle Chat — start new run via LangGraphAgent + EventAdapter."""

    if not query.strip():
        return await _handle_connect(pubsub, template_graph, thread_id, run_id)

    # Duplicate query detection via checkpointer
    try:
        checkpoint_state = await template_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if checkpoint_state and checkpoint_state.values:
            existing_messages = checkpoint_state.values.get("messages", [])
            last_human = None
            for msg in reversed(existing_messages):
                if hasattr(msg, "type") and msg.type == "human":
                    last_human = msg.content
                    break
            if last_human == query:
                logger.info(
                    "Template chat: query already processed for thread %s",
                    thread_id,
                )

                async def _already_done():
                    yield emitter.emit_run_started(thread_id, run_id)
                    template = checkpoint_state.values.get("template")
                    if template is not None:
                        yield emitter.emit_state_snapshot(template)
                    yield emitter.emit_run_finished(thread_id, run_id)

                return StreamingResponse(
                    _already_done(), media_type=emitter.content_type
                )
    except Exception:
        logger.warning("Checkpointer check failed for thread %s", thread_id)

    logger.info("Template chat: new run %s for thread %s", run_id, thread_id)

    try:
        await pubsub.start_run(thread_id, run_id)
    except Exception:
        logger.warning("Failed to register run in Redis")

    # Build RunAgentInput for LangGraphAgent
    existing_template = frontend_state
    if existing_template is None:
        try:
            cp = await template_graph.aget_state(
                {"configurable": {"thread_id": thread_id}}
            )
            if cp and cp.values:
                existing_template = cp.values.get("template")
        except Exception:
            pass

    input_data = RunAgentInput(
        thread_id=thread_id,
        run_id=run_id,
        messages=[UserMessage(id=str(uuid.uuid4()), role="user", content=query)],
        state={"template": existing_template, "version": existing_template.get("version", 0) if existing_template else 0},
        tools=[],
        context=[],
        forwarded_props={"stream_subgraphs": True},
    )

    adapter = EventAdapter()
    event_stream = adapter.stream_events(
        template_agent, input_data, state_snapshot_key="template"
    )

    from stream_reconnection_demo.core.agent_runner import (
        start_agent_task_pubsub_only,
    )

    async def live_stream():
        # Subscribe to Pub/Sub BEFORE starting the background task
        # so no events are missed (especially RUN_STARTED).
        channel_key = pubsub._channel_key(thread_id, run_id)
        ps = pubsub._redis.pubsub()
        await ps.subscribe(channel_key)

        try:
            # Now start the background task — events buffer in subscription
            start_agent_task_pubsub_only(
                pubsub, template_graph, thread_id, run_id, event_stream
            )

            while True:
                msg = await ps.get_message(
                    ignore_subscribe_messages=True, timeout=5.0
                )
                if msg is None:
                    status = await pubsub.get_run_status(thread_id, run_id)
                    if status in ("completed", "error", None):
                        return
                    continue

                if msg["type"] != "message":
                    continue

                raw = msg["data"]
                if raw in (STREAM_END, STREAM_ERROR):
                    return

                try:
                    envelope = json.loads(raw)
                    yield envelope["event"]
                except (json.JSONDecodeError, TypeError):
                    continue
        except Exception:
            logger.exception("Template live stream failed for run %s", run_id)
            yield emitter.emit_run_error("Stream failed")
        finally:
            await ps.unsubscribe(channel_key)
            await ps.aclose()

    return StreamingResponse(live_stream(), media_type=emitter.content_type)


async def _handle_connect(pubsub, template_graph, thread_id: str, run_id: str):
    """Handle Connect — catch-up from checkpointer, then bridge to live Pub/Sub."""

    active_run_id = None
    try:
        active_run_id = await pubsub.get_active_run(thread_id)
    except Exception:
        logger.warning("Failed to check active run for thread %s", thread_id)

    if active_run_id:
        logger.info(
            "Template connect: active run %s, catching up from checkpointer",
            active_run_id,
        )

        async def reconnect_stream():
            channel_key = pubsub._channel_key(thread_id, active_run_id)
            ps = pubsub._redis.pubsub()
            await ps.subscribe(channel_key)

            try:
                # Read checkpointer state for catch-up
                try:
                    checkpoint_state = await template_graph.aget_state(
                        {"configurable": {"thread_id": thread_id}}
                    )
                except Exception:
                    checkpoint_state = None

                # Emit synthetic catch-up events
                async for event in _emit_synthetic_catchup(
                    checkpoint_state.values if checkpoint_state and checkpoint_state.values else {},
                    thread_id,
                    run_id,
                ):
                    yield event

                # Yield live events from Pub/Sub
                while True:
                    message = await ps.get_message(
                        ignore_subscribe_messages=True, timeout=5.0
                    )
                    if message is None:
                        status = await pubsub.get_run_status(
                            thread_id, active_run_id
                        )
                        if status in ("completed", "error"):
                            try:
                                final_state = await template_graph.aget_state(
                                    {"configurable": {"thread_id": thread_id}}
                                )
                                if final_state and final_state.values:
                                    template = final_state.values.get("template")
                                    if template:
                                        yield emitter.emit_state_snapshot(template)
                            except Exception:
                                pass
                            yield emitter.emit_run_finished(thread_id, run_id)
                            return
                        continue

                    if message["type"] != "message":
                        continue

                    try:
                        parsed = json.loads(message["data"])
                        event_data = parsed.get("event", "")
                    except (ValueError, TypeError):
                        continue

                    if event_data in (STREAM_END, STREAM_ERROR):
                        try:
                            final_state = await template_graph.aget_state(
                                {"configurable": {"thread_id": thread_id}}
                            )
                            if final_state and final_state.values:
                                template = final_state.values.get("template")
                                if template:
                                    yield emitter.emit_state_snapshot(template)
                        except Exception:
                            pass
                        yield emitter.emit_run_finished(thread_id, run_id)
                        return

                    yield event_data
            finally:
                await ps.unsubscribe(channel_key)
                await ps.aclose()

        return StreamingResponse(
            reconnect_stream(), media_type=emitter.content_type
        )

    # No active run — check checkpointer for completed state
    try:
        checkpoint_state = await template_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        checkpoint_state = None

    if checkpoint_state and checkpoint_state.values:
        logger.info(
            "Template connect: completed state from checkpointer for thread %s",
            thread_id,
        )

        async def completed_stream():
            async for event in _emit_synthetic_catchup(
                checkpoint_state.values, thread_id, run_id
            ):
                yield event
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            completed_stream(), media_type=emitter.content_type
        )

    # Nothing found
    logger.info("Template connect: no state for thread %s", thread_id)

    async def empty_stream():
        yield emitter.emit_run_started(thread_id, run_id)
        yield emitter.emit_run_finished(thread_id, run_id)

    return StreamingResponse(empty_stream(), media_type=emitter.content_type)


async def _emit_synthetic_catchup(state: dict, thread_id: str, run_id: str):
    """Emit synthetic AG-UI events from checkpointer state for catch-up."""
    yield emitter.emit_run_started(thread_id, run_id)

    # Restore chat history
    messages = state.get("messages", [])
    if messages:
        agui_msgs = emitter.langchain_messages_to_agui(messages)
        if agui_msgs:
            yield emitter.emit_messages_snapshot(agui_msgs)

    # Emit template state snapshot
    template = state.get("template")
    if template:
        yield emitter.emit_state_snapshot(template)
