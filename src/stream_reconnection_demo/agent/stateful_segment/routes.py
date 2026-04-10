"""Stateful Segment endpoint — checkpointer-only catch-up (no Redis List).

Same agent pipeline as /api/v1/segment but catch-up on reconnect
uses only LangGraph MemorySaver checkpointer state. Redis Pub/Sub
is used for live event streaming only.
"""

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from stream_reconnection_demo.core.events import EventEmitter, extract_user_query, get_field
from stream_reconnection_demo.core.middleware import LoggingMiddleware

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)

# Same NODE_META as segment routes
NODE_META = {
    "analyze_requirements": {
        "index": 0, "progress": 0.10, "status": "analyzing",
        "title": "Analyzing Requirements",
        "details": "Parsing user query and extracting segmentation intent...",
        "reasoning": [
            "Parsing the natural language query for segmentation intent... ",
            "Identifying target audience characteristics and filters... ",
            "Mapping keywords to available segmentation fields... ",
        ],
    },
    "extract_entities": {
        "index": 1, "progress": 0.20, "status": "extracting",
        "title": "Extracting Entities",
        "details": "Identifying entity types (locations, behaviors, etc.)...",
        "reasoning": [
            "Scanning query for entity references... ",
            "Classifying entities into categories (location, behavioral, demographic)... ",
            "Building entity map for downstream processing... ",
        ],
    },
    "validate_fields": {
        "index": 2, "progress": 0.30, "status": "validating",
        "title": "Validating Fields",
        "details": "Checking entities against available field catalog...",
        "reasoning": [
            "Cross-referencing detected entities with the field catalog... ",
            "Verifying field availability and compatibility... ",
            "Resolving ambiguous field references... ",
        ],
    },
    "map_operators": {
        "index": 3, "progress": 0.45, "status": "mapping",
        "title": "Mapping Operators",
        "details": "Selecting appropriate operators for each field...",
        "reasoning": [
            "Analyzing field types to determine valid operators... ",
            "Matching user intent to operator semantics... ",
            "Assigning categorical, temporal, and numeric operators... ",
        ],
    },
    "generate_conditions": {
        "index": 4, "progress": 0.55, "status": "generating",
        "title": "Generating Conditions",
        "details": "Building draft condition structures...",
        "reasoning": [
            "Constructing condition objects from operator mappings... ",
            "Determining value ranges and thresholds from context... ",
            "Structuring conditions into logical groups... ",
        ],
    },
    "optimize_conditions": {
        "index": 5, "progress": 0.70, "status": "optimizing",
        "title": "Optimizing Conditions",
        "details": "Simplifying and deduplicating conditions...",
        "reasoning": [
            "Scanning for duplicate field conditions... ",
            "Merging overlapping ranges and redundant filters... ",
            "Optimizing logical grouping for evaluation efficiency... ",
        ],
    },
    "estimate_scope": {
        "index": 6, "progress": 0.85, "status": "estimating",
        "title": "Estimating Scope",
        "details": "Estimating audience size and reach...",
        "reasoning": [
            "Analyzing condition specificity for audience estimation... ",
            "Evaluating filter combination impact on reach... ",
            "Generating scope summary based on condition count and types... ",
        ],
    },
    "build_segment": {
        "index": 7, "progress": 0.95, "status": "building",
        "title": "Building Segment",
        "details": "Generating final segment definition with LLM...",
        "reasoning": [
            "Synthesizing all pre-analyzed context into a coherent segment... ",
            "Applying segmentation best practices and naming conventions... ",
            "Generating structured output with conditions and scope estimate... ",
        ],
    },
}

TOTAL_NODES = len(NODE_META)

# Ordered list of nodes for reconstructing progress from checkpointer
NODE_ORDER = [
    "analyze_requirements", "extract_entities", "validate_fields",
    "map_operators", "generate_conditions", "optimize_conditions",
    "estimate_scope", "build_segment",
]

# State fields that indicate a node has completed
NODE_STATE_FIELDS = {
    "analyze_requirements": "requirements",
    "extract_entities": "entities",
    "validate_fields": "validated_fields",
    "map_operators": "operator_mappings",
    "generate_conditions": "conditions_draft",
    "optimize_conditions": "optimized_conditions",
    "estimate_scope": "scope_estimate",
    "build_segment": "segment",
}


def _extract_step_name_from_sse(event_data: str) -> str | None:
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


async def run_stateful_segment_pipeline(
    segment_graph,
    query: str,
    thread_id: str,
    run_id: str,
) -> AsyncIterator[str]:
    """Run the 8-node segment pipeline and yield AG-UI SSE events.

    Identical to segment pipeline but uses a separate graph instance
    with its own checkpointer namespace.
    """
    message_id = str(uuid.uuid4())

    yield emitter.emit_run_started(thread_id, run_id)

    # Clear previous co-agent state so old segment cards don't render
    # during intermediate steps of this new run
    yield emitter.emit_state_snapshot({})

    # Reset progress status on the frontend immediately
    reset_tool_id = str(uuid.uuid4())
    yield emitter.emit_tool_call_start(reset_tool_id, "update_progress_status", message_id)
    yield emitter.emit_tool_call_args(
        reset_tool_id,
        json.dumps({
            "status": "starting",
            "node": "",
            "node_index": -1,
            "total_nodes": TOTAL_NODES,
        }),
    )
    yield emitter.emit_tool_call_end(reset_tool_id)

    try:
        graph_input = {
            "messages": [HumanMessage(content=query)],
            "segment": None,
            "error": None,
            "current_node": "",
            "requirements": None,
            "entities": [],
            "validated_fields": [],
            "operator_mappings": [],
            "conditions_draft": [],
            "optimized_conditions": [],
            "scope_estimate": None,
        }

        config = {"configurable": {"thread_id": thread_id}}
        result_segment = None

        async for chunk in segment_graph.astream(
            graph_input, config=config, stream_mode="updates"
        ):
            for node_name, node_output in chunk.items():
                if node_name not in NODE_META:
                    continue

                meta = NODE_META[node_name]

                yield emitter.emit_step_start(node_name)

                tool_call_id = str(uuid.uuid4())
                yield emitter.emit_tool_call_start(
                    tool_call_id, "update_progress_status", message_id
                )
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

                activity_id = str(uuid.uuid4())
                yield emitter.emit_activity_snapshot(
                    activity_id, "processing",
                    {"title": meta["title"], "progress": meta["progress"], "details": meta["details"]},
                )

                reasoning_id = str(uuid.uuid4())
                yield emitter.emit_reasoning_start(reasoning_id)
                yield emitter.emit_reasoning_message_start(reasoning_id)
                for step in meta["reasoning"]:
                    yield emitter.emit_reasoning_content(reasoning_id, step)
                    await asyncio.sleep(0.05)
                yield emitter.emit_reasoning_message_end(reasoning_id)
                yield emitter.emit_reasoning_end(reasoning_id)

                delta_ops = []
                for field_name in (
                    "requirements", "entities", "validated_fields",
                    "operator_mappings", "conditions_draft",
                    "optimized_conditions", "scope_estimate",
                ):
                    val = node_output.get(field_name)
                    if val:
                        delta_ops.append({"op": "add", "path": f"/{field_name}", "value": val})
                if delta_ops:
                    yield emitter.emit_state_delta(delta_ops)

                if node_name == "build_segment":
                    result_segment = node_output.get("segment")

                yield emitter.emit_step_finish(node_name)

        if result_segment is None:
            yield emitter.emit_run_error("Segment generation produced no result")
            return

        segment_dict = result_segment.model_dump()

        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()), "processing",
            {"title": "Segment Complete", "progress": 1.0, "details": f"Generated segment: {result_segment.name}"},
        )
        yield emitter.emit_state_snapshot(segment_dict)

        completion_tool_id = str(uuid.uuid4())
        yield emitter.emit_tool_call_start(completion_tool_id, "update_progress_status", message_id)
        yield emitter.emit_tool_call_args(
            completion_tool_id,
            json.dumps({"status": "completed", "node": "build_segment", "node_index": TOTAL_NODES - 1, "total_nodes": TOTAL_NODES}),
        )
        yield emitter.emit_tool_call_end(completion_tool_id)

        summary = f"Created segment: **{result_segment.name}**\n\n{result_segment.description}"
        yield emitter.emit_text_start(message_id, "assistant")
        yield emitter.emit_text_content(message_id, summary)
        yield emitter.emit_text_end(message_id)

    except Exception as e:
        logging.exception("Stateful segment generation failed")
        yield emitter.emit_run_error(str(e))
        return

    yield emitter.emit_run_finished(thread_id, run_id)


def _reconstruct_progress_from_state(
    state: dict, next_nodes: tuple = ()
) -> tuple[str | None, int]:
    """Determine the last completed node from checkpointer state.

    Uses ``next_nodes`` (from ``checkpoint_state.next``) when available —
    this is authoritative because it tells us which node is scheduled to
    run next.  Falls back to state-field inspection for completed runs
    where ``next_nodes`` is empty.

    Returns (last_completed_node, completed_count).
    """
    # Prefer checkpoint metadata: next_nodes tells us exactly which node
    # is queued, so everything before it has completed.
    if next_nodes:
        next_node = next_nodes[0]
        try:
            idx = NODE_ORDER.index(next_node)
            if idx > 0:
                return NODE_ORDER[idx - 1], idx
            return None, 0
        except ValueError:
            pass  # Unknown node — fall through to state inspection

    # Fallback for completed runs (next_nodes is empty) or when metadata
    # is unavailable.  Safe here because a completed pipeline has real
    # values in every field (not just initial empty lists).
    last_completed = None
    completed_count = 0
    for node_name in NODE_ORDER:
        field = NODE_STATE_FIELDS.get(node_name)
        if field and state.get(field) is not None:
            last_completed = node_name
            completed_count += 1
        else:
            break
    return last_completed, completed_count


async def _emit_synthetic_catchup(
    state: dict, thread_id: str, run_id: str, next_nodes: tuple = ()
) -> AsyncIterator[str]:
    """Emit synthetic AG-UI events from checkpointer state for catch-up.

    Reconstructs progress status and state deltas from stored state
    so the frontend can show where the pipeline is.
    """
    message_id = str(uuid.uuid4())
    yield emitter.emit_run_started(thread_id, run_id)

    # Restore chat history from checkpointer messages
    messages = state.get("messages", [])
    if messages:
        agui_msgs = emitter.langchain_messages_to_agui(messages)
        if agui_msgs:
            yield emitter.emit_messages_snapshot(agui_msgs)

    # Emit synthetic progress for each completed node with small delays
    # so the UI can render each step visibly (mimics normal flow pacing)
    _, completed_count = _reconstruct_progress_from_state(state, next_nodes)
    for i in range(completed_count):
        node_name = NODE_ORDER[i]
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

        yield emitter.emit_step_finish(node_name)

    # If pipeline is still running, show indicator for the next node
    if 0 < completed_count < TOTAL_NODES:
        next_node = NODE_ORDER[completed_count]
        next_meta = NODE_META[next_node]
        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()), "processing",
            {"title": next_meta["title"], "progress": next_meta["progress"], "details": "Processing..."},
        )

    # Emit state snapshot if segment exists
    segment = state.get("segment")
    if segment:
        seg_dict = segment.model_dump() if hasattr(segment, "model_dump") else segment
        yield emitter.emit_state_snapshot(seg_dict)

        # Restore completed progress status
        if completed_count == TOTAL_NODES:
            completion_tool_id = str(uuid.uuid4())
            yield emitter.emit_tool_call_start(completion_tool_id, "update_progress_status", message_id)
            yield emitter.emit_tool_call_args(
                completion_tool_id,
                json.dumps({
                    "status": "completed",
                    "node": "build_segment",
                    "node_index": TOTAL_NODES - 1,
                    "total_nodes": TOTAL_NODES,
                }),
            )
            yield emitter.emit_tool_call_end(completion_tool_id)


@router.get("/stateful-segment/state/{thread_id}")
async def get_stateful_segment_state(thread_id: str, request: Request):
    """Return current segment state from checkpointer for a given thread."""
    segment_graph = request.app.state.stateful_segment_graph
    try:
        checkpoint_state = await segment_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if checkpoint_state and checkpoint_state.values:
            segment = checkpoint_state.values.get("segment")
            if segment:
                seg_dict = segment.model_dump() if hasattr(segment, "model_dump") else segment
                return {"segment": seg_dict}
    except Exception:
        logger.warning("Failed to read state for thread %s", thread_id)
    return {"segment": None}


@router.post("/stateful-segment")
async def generate_stateful_segment(request: Request):
    """Single endpoint for stateful-segment — checkpointer-only catch-up.

    Same as /segment but reconnection uses checkpointer state instead
    of Redis List for catch-up. Redis Pub/Sub for live events only.
    """
    body = await request.json()

    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    messages = body.get("messages", [])
    query = extract_user_query(messages)

    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    segment_graph = request.app.state.stateful_segment_graph
    pubsub = request.app.state.pubsub

    logger.info(
        "Stateful-segment request: thread=%s type=%s query=%s",
        thread_id, request_type, query[:50] if query else "(empty)",
    )

    if request_type == "connect":
        return await _handle_stateful_connect(
            pubsub, segment_graph, thread_id, run_id
        )

    return await _handle_stateful_chat(
        pubsub, segment_graph, thread_id, run_id, query
    )


async def _handle_stateful_connect(pubsub, segment_graph, thread_id: str, run_id: str):
    """Handle Connect — catch-up from checkpointer, then bridge to live Pub/Sub."""

    # Check for active run
    active_run_id = None
    try:
        active_run_id = await pubsub.get_active_run(thread_id)
    except Exception:
        logger.warning("Failed to check active run for thread %s", thread_id)

    if active_run_id:
        # Active run — subscribe to pub/sub first, then emit checkpointer state
        logger.info(
            "Stateful connect: active run %s, catching up from checkpointer",
            active_run_id,
        )

        async def reconnect_stream():
            from stream_reconnection_demo.core.pubsub import STREAM_END, STREAM_ERROR

            # Step 1: Subscribe to Pub/Sub (buffer live events)
            channel_key = pubsub._channel_key(thread_id, active_run_id)
            ps = pubsub._redis.pubsub()
            await ps.subscribe(channel_key)

            try:
                # Step 2: Read checkpointer state and track which nodes
                # are already covered so we can deduplicate against
                # live Pub/Sub events that arrive for the same nodes.
                catchup_node_index = -1
                try:
                    checkpoint_state = await segment_graph.aget_state(
                        {"configurable": {"thread_id": thread_id}}
                    )
                except Exception:
                    checkpoint_state = None

                # Step 3: Emit synthetic catch-up events from checkpointer.
                # Pub/Sub events for completed nodes are ephemeral and
                # already lost, so we must reconstruct them from state.
                if checkpoint_state and checkpoint_state.values:
                    next_nodes = getattr(checkpoint_state, "next", ())
                    _, completed_count = _reconstruct_progress_from_state(
                        checkpoint_state.values, next_nodes
                    )
                    catchup_node_index = completed_count - 1

                    async for event in _emit_synthetic_catchup(
                        checkpoint_state.values, thread_id, run_id, next_nodes
                    ):
                        yield event

                # Step 4: Yield live events from Pub/Sub, skipping events
                # for nodes already covered by synthetic catch-up.
                past_catchup = catchup_node_index < 0

                while True:
                    message = await ps.get_message(
                        ignore_subscribe_messages=True, timeout=5.0
                    )
                    if message is None:
                        status = await pubsub.get_run_status(thread_id, active_run_id)
                        if status in ("completed", "error"):
                            if not past_catchup:
                                yield emitter.emit_run_finished(thread_id, run_id)
                            return
                        continue

                    if message["type"] != "message":
                        continue

                    raw = message["data"]

                    # Sentinels are plain strings, not JSON — check first
                    if raw in (STREAM_END, STREAM_ERROR):
                        if not past_catchup:
                            yield emitter.emit_run_finished(thread_id, run_id)
                        return

                    try:
                        parsed = json.loads(raw)
                        event_data = parsed.get("event", "")
                    except (ValueError, TypeError):
                        continue

                    # Skip events for nodes already covered by catch-up.
                    # Start yielding once we see a new node or post-pipeline
                    # event. This prevents progress from jumping backward.
                    if not past_catchup:
                        if "STEP_STARTED" in event_data:
                            step_name = _extract_step_name_from_sse(event_data)
                            if step_name and step_name in NODE_META:
                                if NODE_META[step_name]["index"] > catchup_node_index:
                                    past_catchup = True
                        elif ("TEXT_MESSAGE_START" in event_data
                              or "RUN_FINISHED" in event_data):
                            past_catchup = True

                        if not past_catchup:
                            continue

                    yield event_data
            finally:
                await ps.unsubscribe(channel_key)
                await ps.aclose()

        return StreamingResponse(
            reconnect_stream(), media_type=emitter.content_type
        )

    # No active run — check checkpointer for completed state
    try:
        checkpoint_state = await segment_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        checkpoint_state = None

    if checkpoint_state and checkpoint_state.values:
        logger.info("Stateful connect: completed state from checkpointer for thread %s", thread_id)

        async def completed_stream():
            async for event in _emit_synthetic_catchup(
                checkpoint_state.values, thread_id, run_id,
                getattr(checkpoint_state, "next", ())
            ):
                yield event
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            completed_stream(), media_type=emitter.content_type
        )

    # Nothing found
    logger.info("Stateful connect: no state for thread %s", thread_id)

    async def empty_stream():
        yield emitter.emit_run_started(thread_id, run_id)
        yield emitter.emit_run_finished(thread_id, run_id)

    return StreamingResponse(empty_stream(), media_type=emitter.content_type)


async def _handle_stateful_chat(pubsub, segment_graph, thread_id: str, run_id: str, query: str):
    """Handle Chat — start new run. Pub/Sub only (no List persistence)."""

    if not query.strip():
        # No query — treat like a connect to restore any existing state.
        # This handles the case where CopilotKit sends requestType=chat
        # with empty messages on page reload (frontend lost message history).
        return await _handle_stateful_connect(
            pubsub, segment_graph, thread_id, run_id
        )

    # Check if this query was already processed (prevents CopilotKit re-run loop)
    try:
        checkpoint_state = await segment_graph.aget_state(
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
                logger.info("Stateful chat: query already processed for thread %s, returning empty run", thread_id)

                async def _already_done():
                    yield emitter.emit_run_started(thread_id, run_id)
                    # Do NOT emit MESSAGES_SNAPSHOT here — CopilotKit already
                    # has the correct messages (including streamed assistant text).
                    # Emitting checkpointer messages would REPLACE them.
                    # Replay segment state so CopilotKit retains it
                    # (RUN_STARTED resets co-agent state)
                    segment = checkpoint_state.values.get("segment")
                    if segment is not None:
                        seg_dict = segment.model_dump() if hasattr(segment, "model_dump") else segment
                        yield emitter.emit_state_snapshot(seg_dict)
                    yield emitter.emit_run_finished(thread_id, run_id)

                return StreamingResponse(
                    _already_done(), media_type=emitter.content_type
                )
    except Exception:
        logger.warning("Checkpointer check failed for thread %s", thread_id)

    logger.info("Stateful chat: new run %s for thread %s", run_id, thread_id)

    try:
        await pubsub.start_run(thread_id, run_id)
    except Exception:
        logger.warning("Failed to register run in Redis")

    # Subscribe to Pub/Sub BEFORE starting the task so no events are lost.
    # Without this, the background task publishes RUN_STARTED (and more)
    # before subscribe_and_stream connects, causing "First event must be
    # RUN_STARTED" errors on the frontend.
    from stream_reconnection_demo.core.pubsub import STREAM_END, STREAM_ERROR
    channel_key = pubsub._channel_key(thread_id, run_id)
    ps = pubsub._redis.pubsub()
    await ps.subscribe(channel_key)

    # Now start the background task — events are buffered in `ps`
    pipeline_stream = run_stateful_segment_pipeline(
        segment_graph, query, thread_id, run_id
    )

    from stream_reconnection_demo.core.agent_runner import start_agent_task_pubsub_only
    start_agent_task_pubsub_only(pubsub, segment_graph, thread_id, run_id, pipeline_stream)

    # Stream from the already-subscribed channel
    async def live_stream():
        try:
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

                # Sentinels are plain strings, not JSON envelopes
                if raw in (STREAM_END, STREAM_ERROR):
                    return

                try:
                    envelope = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                yield envelope["event"]
        except Exception:
            logger.exception("Stateful live stream failed for run %s", run_id)
            yield emitter.emit_run_error("Stream failed")
        finally:
            await ps.unsubscribe(channel_key)
            await ps.aclose()

    return StreamingResponse(
        live_stream(), media_type=emitter.content_type
    )
