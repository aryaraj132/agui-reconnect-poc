"""Template agent endpoint — ag-ui-langgraph + Redis Pub/Sub.

Uses LangGraphAgent for automatic AG-UI event generation.
Checkpointer is the single source of truth for catch-up.
Redis Pub/Sub for live event streaming only (no List).
"""

from __future__ import annotations

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
from stream_reconnection_demo.core.reconnect import (
    ReconnectConfig,
    handle_checkpointer_connect,
)

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)

# Node metadata for progress tracking.
# generate_template and modify_template share index 0 (conditional routing).
NODE_META = {
    "generate_template": {
        "index": 0, "progress": 0.15, "status": "generating",
        "title": "Generating Template",
        "details": "Creating email template with LLM...",
    },
    "modify_template": {
        "index": 0, "progress": 0.15, "status": "modifying",
        "title": "Modifying Template",
        "details": "Applying changes to template...",
    },
    "analyze_template": {
        "index": 1, "progress": 0.50, "status": "analyzing",
        "title": "Analyzing Template",
        "details": "Running HTML analysis (subject, colors, typography, structure)...",
    },
    "quality_check": {
        "index": 2, "progress": 0.85, "status": "checking",
        "title": "Quality Check",
        "details": "Checking spelling, tone, and CTA effectiveness...",
    },
}

TOTAL_NODES = 3

# Ordered node lists for the two execution paths
NODE_ORDER_GENERATE = ["generate_template", "analyze_template", "quality_check"]
NODE_ORDER_MODIFY = ["modify_template", "analyze_template", "quality_check"]

# State fields that indicate a node has completed
NODE_STATE_FIELDS = {
    "generate_template": "template",
    "modify_template": "template",
    "analyze_template": "overall_assessment",
    "quality_check": "quality_summary",
}


def _determine_node_order(state: dict, next_nodes: tuple = ()) -> list[str]:
    """Determine which execution path was taken (generate vs modify)."""
    # If next_nodes mentions a specific first node, use that path
    if next_nodes:
        first = next_nodes[0]
        if first == "generate_template":
            return NODE_ORDER_GENERATE
        if first == "modify_template":
            return NODE_ORDER_MODIFY

    # If template exists, determine from version
    version = state.get("version", 0)
    if version > 1:
        return NODE_ORDER_MODIFY
    if version == 1:
        return NODE_ORDER_GENERATE

    # Fallback: check if template field is populated
    if state.get("template") is not None:
        return NODE_ORDER_GENERATE

    return NODE_ORDER_GENERATE


def _reconstruct_progress_from_state(
    state: dict, next_nodes: tuple = ()
) -> tuple[str | None, int, list[str]]:
    """Determine the last completed node from checkpointer state.

    Returns (last_completed_node, completed_count, node_order).
    """
    node_order = _determine_node_order(state, next_nodes)

    # Prefer checkpoint metadata: next_nodes tells us exactly which node
    # is queued, so everything before it has completed.
    if next_nodes:
        next_node = next_nodes[0]
        try:
            idx = node_order.index(next_node)
            if idx > 0:
                return node_order[idx - 1], idx, node_order
            return None, 0, node_order
        except ValueError:
            pass  # Unknown node — fall through to state inspection

    # Fallback for completed runs (next_nodes is empty).
    last_completed = None
    completed_count = 0
    for node_name in node_order:
        field = NODE_STATE_FIELDS.get(node_name)
        if field and state.get(field) is not None:
            last_completed = node_name
            completed_count += 1
        else:
            break
    return last_completed, completed_count, node_order


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
        return await handle_checkpointer_connect(pubsub, template_graph, thread_id, run_id, RECONNECT_CONFIG)

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
        return await handle_checkpointer_connect(pubsub, template_graph, thread_id, run_id, RECONNECT_CONFIG)

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
        template_agent, input_data,
        state_snapshot_key="template",
        allowed_step_names=set(NODE_META.keys()),
        reasoning_step_names={"analyze_template"},
    )

    from stream_reconnection_demo.core.agent_runner import (
        start_agent_task_pubsub_only,
    )

    async def live_stream():
        # Subscribe BEFORE starting the background task so no events are missed.
        async with pubsub.open_subscription(thread_id, run_id) as events:
            # Now start the background task — events buffer in subscription
            start_agent_task_pubsub_only(
                pubsub, template_graph, thread_id, run_id, event_stream
            )

            async for event in events:
                yield event

    return StreamingResponse(live_stream(), media_type=emitter.content_type)


def _emit_analysis_reasoning(state: dict):
    """Emit analysis results as a single reasoning panel for catch-up.

    Formats each AnalysisResult as readable paragraphs (aspect, severity,
    findings, suggestions) instead of raw JSON.
    """
    analyses = state.get("analyses", [])
    overall = state.get("overall_assessment")
    if not analyses and not overall:
        return

    mid = str(uuid.uuid4())
    yield emitter.emit_reasoning_start(mid)
    yield emitter.emit_reasoning_message_start(mid)

    for i, analysis in enumerate(analyses):
        aspect = analysis.get("aspect", "Unknown").replace("_", " ").title()
        severity = analysis.get("severity", "")
        findings = analysis.get("findings", "")
        suggestions = analysis.get("suggestions", [])

        content = f"**{aspect}** (severity: {severity})\n\n{findings}"
        if suggestions:
            content += "\n\nSuggestions:\n" + "\n".join(
                f"- {s}" for s in suggestions
            )
        if i < len(analyses) - 1:
            content += "\n\n---\n\n"
        yield emitter.emit_reasoning_content(mid, content)

    if overall:
        needs_improvement = state.get("needs_improvement", False)
        yield emitter.emit_reasoning_content(
            mid,
            f"\n\n---\n\n**Overall Assessment**\n\n{overall}\n\n"
            f"Needs improvement: {'Yes' if needs_improvement else 'No'}",
        )

    yield emitter.emit_reasoning_message_end(mid)
    yield emitter.emit_reasoning_end(mid)


def _emit_quality_text(state: dict):
    """Emit individual quality reports and summary as text messages for catch-up."""
    for field in ("spelling_report", "tone_report", "cta_report", "quality_summary"):
        content = state.get(field)
        if content:
            mid = str(uuid.uuid4())
            yield emitter.emit_text_start(mid, "assistant")
            yield emitter.emit_text_content(mid, content)
            yield emitter.emit_text_end(mid)


async def _emit_synthetic_catchup(state: dict, thread_id: str, run_id: str, next_nodes: tuple = ()):
    """Emit synthetic AG-UI events from checkpointer state for catch-up.

    Reconstructs per-node progress and state snapshots so the frontend
    can show where the pipeline is.
    """
    message_id = str(uuid.uuid4())
    yield emitter.emit_run_started(thread_id, run_id)

    # Restore chat history from checkpointer messages
    messages = state.get("messages", [])
    if messages:
        agui_msgs = emitter.langchain_messages_to_agui(messages)
        if agui_msgs:
            yield emitter.emit_messages_snapshot(agui_msgs)

    # Emit synthetic progress for each completed node
    _, completed_count, node_order = _reconstruct_progress_from_state(state, next_nodes)
    for i in range(completed_count):
        node_name = node_order[i]
        meta = NODE_META[node_name]

        yield emitter.emit_step_start(node_name)

        tool_call_id = str(uuid.uuid4())
        yield emitter.emit_tool_call_start(tool_call_id, "update_progress_status", message_id)
        yield emitter.emit_tool_call_args(
            tool_call_id,
            json.dumps({
                "status": meta["status"],
                "node": node_name,
                "node_index": meta["index"],
                "total_nodes": TOTAL_NODES,
            }),
        )
        yield emitter.emit_tool_call_end(tool_call_id)

        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()), "processing",
            {"title": meta["title"], "progress": meta["progress"], "details": meta["details"]},
        )

        # Restore analysis content as text messages after relevant nodes
        if node_name == "analyze_template":
            for event in _emit_analysis_reasoning(state):
                yield event
        elif node_name == "quality_check":
            for event in _emit_quality_text(state):
                yield event

        yield emitter.emit_step_finish(node_name)

    # If pipeline is still running, show indicator for the next node
    if 0 < completed_count < TOTAL_NODES:
        next_node = node_order[completed_count]
        next_meta = NODE_META[next_node]
        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()), "processing",
            {"title": next_meta["title"], "progress": next_meta["progress"], "details": "Processing..."},
        )

    # Emit state snapshots for template and quality summary
    template = state.get("template")
    if template:
        yield emitter.emit_state_snapshot(template)

    # Restore completed progress status
    if completed_count == TOTAL_NODES:
        completion_tool_id = str(uuid.uuid4())
        yield emitter.emit_tool_call_start(completion_tool_id, "update_progress_status", message_id)
        yield emitter.emit_tool_call_args(
            completion_tool_id,
            json.dumps({
                "status": "completed",
                "node": node_order[-1],
                "node_index": TOTAL_NODES - 1,
                "total_nodes": TOTAL_NODES,
            }),
        )
        yield emitter.emit_tool_call_end(completion_tool_id)


def _get_completed_count(state: dict, next_nodes: tuple = ()) -> int:
    """Return just the completed_count for ReconnectConfig."""
    _, completed_count, _ = _reconstruct_progress_from_state(state, next_nodes)
    return completed_count


RECONNECT_CONFIG = ReconnectConfig(
    node_meta=NODE_META,
    state_snapshot_key="template",
    emit_catchup=_emit_synthetic_catchup,
    get_completed_count=_get_completed_count,
)
