"""Template editor endpoints -- FE-tools and BE-only modes.

Both endpoints follow the same pattern as the template agent:
- Checkpointer is the single source of truth for catch-up.
- Redis Pub/Sub for live event streaming only.
- LangGraphAgent + EventAdapter for AG-UI event generation.
"""

from __future__ import annotations

import logging
import uuid

from ag_ui.core import RunAgentInput, UserMessage
from ag_ui_langgraph import LangGraphAgent
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stream_reconnection_demo.core.event_adapter import EventAdapter
from stream_reconnection_demo.core.events import (
    EventEmitter,
    extract_user_query,
    get_field,
)
from stream_reconnection_demo.core.reconnect import (
    ReconnectConfig,
    handle_checkpointer_connect,
)

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)


# ── Reconnect helpers ────────────────────────────────────────────────


async def _emit_synthetic_catchup(
    state: dict, thread_id: str, run_id: str, next_nodes: tuple = ()
):
    """Emit synthetic events from checkpointer state for catch-up."""
    yield emitter.emit_run_started(thread_id, run_id)

    messages = state.get("messages", [])
    if messages:
        agui_msgs = emitter.langchain_messages_to_agui(messages)
        if agui_msgs:
            yield emitter.emit_messages_snapshot(agui_msgs)

    template = state.get("template")
    if template:
        yield emitter.emit_state_snapshot(template)


def _get_completed_count(state: dict, next_nodes: tuple = ()) -> int:
    """Return completed count -- for create_react_agent, 1 if template exists."""
    return 1 if state.get("template") else 0


RECONNECT_CONFIG = ReconnectConfig(
    node_meta={"agent": {"index": 0}, "tools": {"index": 1}},
    state_snapshot_key="template",
    emit_catchup=_emit_synthetic_catchup,
    get_completed_count=_get_completed_count,
)


# ── Shared chat handler ──────────────────────────────────────────────


async def _handle_chat(
    pubsub,
    graph,
    agent_wrapper: LangGraphAgent,
    thread_id: str,
    run_id: str,
    query: str,
    frontend_state: dict | None,
    suppress_tool_calls: bool = False,
):
    """Handle a chat request -- shared by both FE-tools and BE-only."""

    if not query.strip():
        return await handle_checkpointer_connect(
            pubsub, graph, thread_id, run_id, RECONNECT_CONFIG
        )

    # Duplicate query detection
    try:
        checkpoint_state = await graph.aget_state(
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
                logger.info("Duplicate query for thread %s", thread_id)

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

    logger.info("Template editor chat: run %s for thread %s", run_id, thread_id)

    try:
        await pubsub.start_run(thread_id, run_id)
    except Exception:
        logger.warning("Failed to register run in Redis")

    # Build state from frontend or checkpointer
    existing_template = frontend_state
    if existing_template is None:
        try:
            cp = await graph.aget_state(
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
        state={
            "template": existing_template,
            "version": existing_template.get("version", 0) if existing_template else 0,
        },
        tools=[],
        context=[],
        forwarded_props={},
    )

    adapter = EventAdapter()
    event_stream = adapter.stream_events(
        agent_wrapper,
        input_data,
        state_snapshot_key="template",
        suppress_tool_calls=suppress_tool_calls,
    )

    from stream_reconnection_demo.core.agent_runner import (
        start_agent_task_pubsub_only,
    )

    async def live_stream():
        async with pubsub.open_subscription(thread_id, run_id) as events:
            start_agent_task_pubsub_only(
                pubsub, graph, thread_id, run_id, event_stream
            )
            async for event in events:
                yield event

    return StreamingResponse(live_stream(), media_type=emitter.content_type)


# ── FE-tools endpoint ───────────────────────────────────────────────


@router.post("/template-editor/fe-tools")
async def handle_fe_tools(request: Request):
    body = await request.json()

    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    messages = body.get("messages", [])
    query = extract_user_query(messages)
    frontend_state = body.get("state")

    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    graph = request.app.state.te_fe_graph
    agent_wrapper = request.app.state.te_fe_agent
    pubsub = request.app.state.pubsub

    logger.info("TE FE-tools: thread=%s type=%s", thread_id, request_type)

    if request_type == "connect":
        return await handle_checkpointer_connect(
            pubsub, graph, thread_id, run_id, RECONNECT_CONFIG
        )

    return await _handle_chat(
        pubsub, graph, agent_wrapper, thread_id, run_id, query, frontend_state,
        suppress_tool_calls=False,
    )


# ── BE-only endpoint ─────────────────────────────────────────────────


@router.post("/template-editor/be-only")
async def handle_be_only(request: Request):
    body = await request.json()

    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    messages = body.get("messages", [])
    query = extract_user_query(messages)
    frontend_state = body.get("state")

    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    graph = request.app.state.te_be_graph
    agent_wrapper = request.app.state.te_be_agent
    pubsub = request.app.state.pubsub

    logger.info("TE BE-only: thread=%s type=%s", thread_id, request_type)

    if request_type == "connect":
        return await handle_checkpointer_connect(
            pubsub, graph, thread_id, run_id, RECONNECT_CONFIG
        )

    return await _handle_chat(
        pubsub, graph, agent_wrapper, thread_id, run_id, query, frontend_state,
        suppress_tool_calls=True,
    )
