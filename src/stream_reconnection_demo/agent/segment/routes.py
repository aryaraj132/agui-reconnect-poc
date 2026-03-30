import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from stream_reconnection_demo.core.events import EventEmitter, extract_user_query, get_field
from stream_reconnection_demo.core.agent_runner import start_agent_task

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()

# Metadata for each node in the pipeline
NODE_META = {
    "analyze_requirements": {
        "index": 0,
        "progress": 0.10,
        "status": "analyzing",
        "title": "Analyzing Requirements",
        "details": "Parsing user query and extracting segmentation intent...",
        "reasoning": [
            "Parsing the natural language query for segmentation intent... ",
            "Identifying target audience characteristics and filters... ",
            "Mapping keywords to available segmentation fields... ",
        ],
    },
    "extract_entities": {
        "index": 1,
        "progress": 0.20,
        "status": "extracting",
        "title": "Extracting Entities",
        "details": "Identifying entity types (locations, behaviors, etc.)...",
        "reasoning": [
            "Scanning query for entity references... ",
            "Classifying entities into categories (location, behavioral, demographic)... ",
            "Building entity map for downstream processing... ",
        ],
    },
    "validate_fields": {
        "index": 2,
        "progress": 0.30,
        "status": "validating",
        "title": "Validating Fields",
        "details": "Checking entities against available field catalog...",
        "reasoning": [
            "Cross-referencing detected entities with the field catalog... ",
            "Verifying field availability and compatibility... ",
            "Resolving ambiguous field references... ",
        ],
    },
    "map_operators": {
        "index": 3,
        "progress": 0.45,
        "status": "mapping",
        "title": "Mapping Operators",
        "details": "Selecting appropriate operators for each field...",
        "reasoning": [
            "Analyzing field types to determine valid operators... ",
            "Matching user intent to operator semantics... ",
            "Assigning categorical, temporal, and numeric operators... ",
        ],
    },
    "generate_conditions": {
        "index": 4,
        "progress": 0.55,
        "status": "generating",
        "title": "Generating Conditions",
        "details": "Building draft condition structures...",
        "reasoning": [
            "Constructing condition objects from operator mappings... ",
            "Determining value ranges and thresholds from context... ",
            "Structuring conditions into logical groups... ",
        ],
    },
    "optimize_conditions": {
        "index": 5,
        "progress": 0.70,
        "status": "optimizing",
        "title": "Optimizing Conditions",
        "details": "Simplifying and deduplicating conditions...",
        "reasoning": [
            "Scanning for duplicate field conditions... ",
            "Merging overlapping ranges and redundant filters... ",
            "Optimizing logical grouping for evaluation efficiency... ",
        ],
    },
    "estimate_scope": {
        "index": 6,
        "progress": 0.85,
        "status": "estimating",
        "title": "Estimating Scope",
        "details": "Estimating audience size and reach...",
        "reasoning": [
            "Analyzing condition specificity for audience estimation... ",
            "Evaluating filter combination impact on reach... ",
            "Generating scope summary based on condition count and types... ",
        ],
    },
    "build_segment": {
        "index": 7,
        "progress": 0.95,
        "status": "building",
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

# Fields that may appear in node output and should be emitted as state deltas
_DELTA_FIELDS = [
    "requirements",
    "entities",
    "validated_fields",
    "operator_mappings",
    "conditions_draft",
    "optimized_conditions",
    "scope_estimate",
]


async def run_segment_pipeline(
    segment_graph,
    query: str,
    thread_id: str,
    run_id: str,
) -> AsyncIterator[str]:
    """Stream AG-UI events from the LangGraph segment pipeline.

    Yields SSE-encoded event strings for each pipeline step including
    progress, reasoning, state deltas, and the final segment result.
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

    config = {"configurable": {"thread_id": thread_id}}

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

        result_segment = None

        async for chunk in segment_graph.astream(
            graph_input, config=config, stream_mode="updates"
        ):
            # chunk is {node_name: state_update_dict}
            for node_name, node_output in chunk.items():
                if node_name not in NODE_META:
                    continue

                meta = NODE_META[node_name]

                # --- STEP START ---
                yield emitter.emit_step_start(node_name)

                # --- TOOL CALL: update_progress_status ---
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

                # --- ACTIVITY SNAPSHOT ---
                activity_id = str(uuid.uuid4())
                yield emitter.emit_activity_snapshot(
                    activity_id,
                    "processing",
                    {
                        "title": meta["title"],
                        "progress": meta["progress"],
                        "details": meta["details"],
                    },
                )

                # --- REASONING EVENTS ---
                reasoning_id = str(uuid.uuid4())
                yield emitter.emit_reasoning_start(reasoning_id)
                yield emitter.emit_reasoning_message_start(reasoning_id)
                for step in meta["reasoning"]:
                    yield emitter.emit_reasoning_content(reasoning_id, step)
                    await asyncio.sleep(0.05)
                yield emitter.emit_reasoning_message_end(reasoning_id)
                yield emitter.emit_reasoning_end(reasoning_id)

                # --- STATE DELTA for intermediate results ---
                delta_ops = []
                for field_name in _DELTA_FIELDS:
                    if field_name in node_output and node_output[field_name]:
                        delta_ops.append({
                            "op": "add",
                            "path": f"/{field_name}",
                            "value": node_output[field_name],
                        })
                if delta_ops:
                    yield emitter.emit_state_delta(delta_ops)

                # Capture segment from build_segment node
                if node_name == "build_segment":
                    result_segment = node_output.get("segment")

                # --- STEP FINISH ---
                yield emitter.emit_step_finish(node_name)

        # --- ERROR CHECK ---
        if result_segment is None:
            yield emitter.emit_run_error("Segment generation produced no result")
            return

        # --- FINAL STATE SNAPSHOT ---
        segment_dict = result_segment.model_dump()

        # Activity: 100%
        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()),
            "processing",
            {
                "title": "Segment Complete",
                "progress": 1.0,
                "details": f"Generated segment: {result_segment.name}",
            },
        )

        yield emitter.emit_state_snapshot(segment_dict)

        # --- TOOL CALL: update_progress_status (completed) ---
        completion_tool_id = str(uuid.uuid4())
        yield emitter.emit_tool_call_start(
            completion_tool_id, "update_progress_status", message_id
        )
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

        # --- TEXT MESSAGE ---
        summary = f"Created segment: **{result_segment.name}**\n\n{result_segment.description}"
        yield emitter.emit_text_start(message_id, "assistant")
        yield emitter.emit_text_content(message_id, summary)
        yield emitter.emit_text_end(message_id)

    except Exception as e:
        logging.exception("Segment generation failed")
        yield emitter.emit_run_error(str(e))
        return

    yield emitter.emit_run_finished(thread_id, run_id)


# ---------------------------------------------------------------------------
# Intent-based request handlers
# ---------------------------------------------------------------------------


async def _handle_connect(pubsub, segment_graph, thread_id, run_id):
    """Handle a 'connect' request — reconnect to active run or replay state.

    1. If an active run exists in Redis, catch up and follow live events.
    2. If no active run but a checkpointer snapshot exists, replay it.
    3. If nothing found, return an empty run (started + finished).
    """
    # Check for an active run in Redis
    active_run_id = None
    try:
        active_run_id = await pubsub.get_active_run(thread_id)
    except Exception:
        logging.warning("Failed to check active run for thread %s", thread_id)

    if active_run_id:
        logging.info(
            "Connect: active run %s found for thread %s — catching up",
            active_run_id, thread_id,
        )

        # Read checkpointer for previous conversation history
        try:
            checkpoint_state = await segment_graph.aget_state(
                {"configurable": {"thread_id": thread_id}}
            )
        except Exception:
            checkpoint_state = None

        async def _reconnect_with_history():
            first_event = True
            async for event in pubsub.catch_up_and_follow(thread_id, active_run_id):
                yield event
                if first_event:
                    first_event = False
                    # Inject MESSAGES_SNAPSHOT right after RUN_STARTED
                    # so previous conversation history is restored
                    if checkpoint_state and checkpoint_state.values:
                        messages = checkpoint_state.values.get("messages", [])
                        if messages:
                            agui_msgs = emitter.langchain_messages_to_agui(messages)
                            if agui_msgs:
                                yield emitter.emit_messages_snapshot(agui_msgs)

        return StreamingResponse(
            _reconnect_with_history(), media_type=emitter.content_type,
        )

    # No active run — try checkpointer for completed state
    try:
        checkpoint_state = await segment_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        logging.warning("Failed to read checkpointer for thread %s", thread_id)
        checkpoint_state = None

    if checkpoint_state and checkpoint_state.values:
        logging.info(
            "Connect: checkpointer state found for thread %s — replaying",
            thread_id,
        )

        async def _replay_checkpoint():
            yield emitter.emit_run_started(thread_id, run_id)

            # Restore chat history from checkpointer messages
            messages = checkpoint_state.values.get("messages", [])
            if messages:
                agui_msgs = emitter.langchain_messages_to_agui(messages)
                if agui_msgs:
                    yield emitter.emit_messages_snapshot(agui_msgs)

            # Replay segment state so CopilotKit can render the segment card
            segment = checkpoint_state.values.get("segment")
            if segment is not None:
                segment_dict = segment.model_dump() if hasattr(segment, "model_dump") else segment
                yield emitter.emit_state_snapshot(segment_dict)

                # Restore completed progress status
                msg_id = str(uuid.uuid4())
                tool_id = str(uuid.uuid4())
                yield emitter.emit_tool_call_start(tool_id, "update_progress_status", msg_id)
                yield emitter.emit_tool_call_args(
                    tool_id,
                    json.dumps({
                        "status": "completed",
                        "node": "build_segment",
                        "node_index": TOTAL_NODES - 1,
                        "total_nodes": TOTAL_NODES,
                    }),
                )
                yield emitter.emit_tool_call_end(tool_id)

            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            _replay_checkpoint(), media_type=emitter.content_type
        )

    # Nothing found — empty run
    logging.info(
        "Connect: no state found for thread %s — returning empty run",
        thread_id,
    )

    async def _empty_run():
        yield emitter.emit_run_started(thread_id, run_id)
        yield emitter.emit_run_finished(thread_id, run_id)

    return StreamingResponse(
        _empty_run(), media_type=emitter.content_type
    )


async def _handle_chat(pubsub, segment_graph, thread_id, run_id, query):
    """Handle a 'chat' request — start a new agent run or return completed state.

    If the query is empty, return the current checkpointer state (if any).
    If a query is provided, start the agent pipeline in the background and
    stream events via catch-up-and-follow.
    """
    if not query or not query.strip():
        # No query — treat like a connect to restore any existing state.
        # This handles the case where CopilotKit sends requestType=chat
        # with empty messages on page reload (frontend lost message history).
        return await _handle_connect(pubsub, segment_graph, thread_id, run_id)

    # Check if this query was already processed (prevents CopilotKit re-run loop).
    # CopilotKit re-sends the full messages array after each run completes.
    # Return a minimal empty run so CopilotKit is satisfied without corrupting state.
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
                logging.info("Chat: query already processed for thread %s, returning empty run", thread_id)

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
        logging.warning("Checkpointer check failed for thread %s", thread_id)

    # Has a query — start agent pipeline in the background
    try:
        await pubsub.start_run(thread_id, run_id)
    except Exception:
        logging.warning("Redis start_run failed for run %s", run_id)

    pipeline_stream = run_segment_pipeline(
        segment_graph, query, thread_id, run_id
    )
    start_agent_task(pubsub, segment_graph, thread_id, run_id, pipeline_stream)

    # Let the background task start publishing before we begin following
    await asyncio.sleep(0.1)

    return StreamingResponse(
        pubsub.catch_up_and_follow(thread_id, run_id),
        media_type=emitter.content_type,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/segment/state/{thread_id}")
async def get_segment_state(thread_id: str, request: Request):
    """Return the current segment state from the checkpointer for a given thread.

    Used by the frontend to restore state on reconnect when CopilotKit's
    runtime does not forward agent/connect to the backend.
    """
    segment_graph = request.app.state.segment_graph
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
        logging.warning("Failed to read state for thread %s", thread_id)
    return {"segment": None}


@router.post("/segment")
async def generate_segment(request: Request):
    """Single endpoint for segment pipeline — handles new runs, reconnections,
    and mid-execution joins via intent detection from request metadata.
    """
    body = await request.json()
    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    query = extract_user_query(body.get("messages", []))

    segment_graph = request.app.state.segment_graph
    pubsub = request.app.state.pubsub

    # Detect request type from metadata
    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    logging.info(
        "Segment request: type=%s thread=%s run=%s query=%s",
        request_type, thread_id, run_id, query[:80] if query else "(empty)",
    )

    if request_type == "connect":
        return await _handle_connect(pubsub, segment_graph, thread_id, run_id)

    # Default: chat
    return await _handle_chat(pubsub, segment_graph, thread_id, run_id, query)
