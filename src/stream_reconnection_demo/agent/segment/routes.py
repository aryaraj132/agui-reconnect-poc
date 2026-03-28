import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from stream_reconnection_demo.core.events import EventEmitter, extract_user_query, get_field
from stream_reconnection_demo.core.history import thread_store
from stream_reconnection_demo.core.middleware import (
    HistoryMiddleware,
    LoggingMiddleware,
    RedisStreamMiddleware,
)

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


@router.post("/segment")
async def generate_segment(request: Request):
    body = await request.json()
    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    query = extract_user_query(body.get("messages", []))

    # DEBUG: dump full body to trace what CopilotKit/LangGraphHttpAgent sends
    import json as _json
    logging.info(
        "POST /segment — thread_id=%s, run_id=%s, query=%r\n  BODY: %s",
        thread_id, run_id, query[:80] if query else "",
        _json.dumps({k: v for k, v in body.items() if k != "messages"}, default=str),
    )
    logging.info(
        "POST /segment — messages count=%d, message_roles=%s",
        len(body.get("messages", [])),
        [m.get("role", "?") for m in body.get("messages", [])],
    )

    segment_graph = request.app.state.segment_graph
    redis_manager = request.app.state.redis_manager

    # Guard 1: empty query (e.g. CopilotKit's agent/connect with messages: [])
    if not query.strip():
        logging.info(
            "Guard 1: empty query for thread %s (likely agent/connect)",
            thread_id,
        )
        thread = thread_store.get_thread(thread_id)

        async def empty_query_stream():
            yield emitter.emit_run_started(thread_id, run_id)
            if thread and thread["messages"]:
                yield emitter.emit_messages_snapshot(thread["messages"])
            if thread and thread["state"]:
                yield emitter.emit_state_snapshot(thread["state"])
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            empty_query_stream(), media_type=emitter.content_type
        )

    # Guard 2: Redis has an active or completed stream for this thread.
    # Prevents CopilotKit's connectAgent() from triggering a new generation
    # when it replays messages on page reload — even after backend restart
    # (ThreadStore empty but Redis persists).
    try:
        existing_run = await redis_manager.find_stream(thread_id)
    except Exception:
        existing_run = None

    if existing_run:
        logging.info(
            "Guard 2: existing stream for thread %s (run %s) — returning stored state",
            thread_id, existing_run,
        )
        thread = thread_store.get_thread(thread_id)

        async def already_exists_stream():
            yield emitter.emit_run_started(thread_id, run_id)
            if thread and thread["messages"]:
                yield emitter.emit_messages_snapshot(thread["messages"])
            if thread and thread["state"]:
                yield emitter.emit_state_snapshot(thread["state"])
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            already_exists_stream(), media_type=emitter.content_type
        )

    # Guard 3: ThreadStore has completed state with same query (no Redis)
    thread = thread_store.get_or_create_thread(thread_id, "segment")
    if (
        thread["state"]
        and thread["messages"]
        and thread["messages"][-1].get("role") == "assistant"
    ):
        last_user_msg = ""
        for msg in reversed(thread["messages"]):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break
        if last_user_msg == query:
            logging.info(
                "Guard 3: same query already completed for thread %s",
                thread_id,
            )

            async def completed_stream():
                yield emitter.emit_run_started(thread_id, run_id)
                yield emitter.emit_messages_snapshot(thread["messages"])
                yield emitter.emit_state_snapshot(thread["state"])
                yield emitter.emit_run_finished(thread_id, run_id)

            return StreamingResponse(
                completed_stream(), media_type=emitter.content_type
            )

    prior_messages = list(thread["messages"])
    thread_store.add_message(thread_id, {"role": "user", "content": query})

    # Register this run in Redis
    try:
        await redis_manager.start_run(thread_id, run_id)
    except Exception:
        logging.warning("Redis start_run failed, streaming without persistence")

    async def event_stream():
        message_id = str(uuid.uuid4())

        yield emitter.emit_run_started(thread_id, run_id)

        if prior_messages:
            yield emitter.emit_messages_snapshot(prior_messages)

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
                graph_input, stream_mode="updates"
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
                    if "requirements" in node_output and node_output["requirements"]:
                        delta_ops.append({
                            "op": "add", "path": "/requirements",
                            "value": node_output["requirements"],
                        })
                    if "entities" in node_output and node_output["entities"]:
                        delta_ops.append({
                            "op": "add", "path": "/entities",
                            "value": node_output["entities"],
                        })
                    if "validated_fields" in node_output and node_output["validated_fields"]:
                        delta_ops.append({
                            "op": "add", "path": "/validated_fields",
                            "value": node_output["validated_fields"],
                        })
                    if "operator_mappings" in node_output and node_output["operator_mappings"]:
                        delta_ops.append({
                            "op": "add", "path": "/operator_mappings",
                            "value": node_output["operator_mappings"],
                        })
                    if "conditions_draft" in node_output and node_output["conditions_draft"]:
                        delta_ops.append({
                            "op": "add", "path": "/conditions_draft",
                            "value": node_output["conditions_draft"],
                        })
                    if "optimized_conditions" in node_output and node_output["optimized_conditions"]:
                        delta_ops.append({
                            "op": "add", "path": "/optimized_conditions",
                            "value": node_output["optimized_conditions"],
                        })
                    if "scope_estimate" in node_output and node_output["scope_estimate"]:
                        delta_ops.append({
                            "op": "add", "path": "/scope_estimate",
                            "value": node_output["scope_estimate"],
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
            thread_store.update_state(thread_id, segment_dict)

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

            thread_store.add_message(
                thread_id, {"role": "assistant", "content": summary}
            )

        except Exception as e:
            logging.exception("Segment generation failed")
            yield emitter.emit_run_error(str(e))
            return

        yield emitter.emit_run_finished(thread_id, run_id)

    raw_stream = event_stream()
    stream = LoggingMiddleware().apply(
        HistoryMiddleware(store=thread_store, thread_id=thread_id).apply(
            RedisStreamMiddleware(redis_manager, thread_id, run_id).apply(
                raw_stream
            )
        )
    )

    return StreamingResponse(stream, media_type=emitter.content_type)
