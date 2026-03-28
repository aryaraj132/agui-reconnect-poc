import asyncio
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
        "progress": 0.2,
        "title": "Analyzing Requirements",
        "details": "Parsing user query and extracting key intents...",
        "reasoning": [
            "Parsing the natural language query for segmentation intent... ",
            "Identifying target audience characteristics and filters... ",
            "Mapping keywords to available segmentation fields... ",
        ],
    },
    "validate_fields": {
        "progress": 0.4,
        "title": "Validating Fields",
        "details": "Checking detected fields against available catalog...",
        "reasoning": [
            "Cross-referencing detected fields with the field catalog... ",
            "Verifying field availability and compatibility... ",
            "Resolving ambiguous field references... ",
        ],
    },
    "generate_conditions": {
        "progress": 0.65,
        "title": "Generating Conditions",
        "details": "Building condition structures from validated fields...",
        "reasoning": [
            "Selecting appropriate operators for each field type... ",
            "Determining value ranges and thresholds from context... ",
            "Structuring conditions into logical groups... ",
        ],
    },
    "build_segment": {
        "progress": 0.9,
        "title": "Building Segment",
        "details": "Generating final segment definition with LLM...",
        "reasoning": [
            "Synthesizing all pre-analyzed context into a coherent segment... ",
            "Applying segmentation best practices and naming conventions... ",
            "Estimating audience scope based on condition specificity... ",
        ],
    },
}


@router.post("/segment")
async def generate_segment(request: Request):
    body = await request.json()
    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    query = extract_user_query(body.get("messages", []))

    segment_graph = request.app.state.segment_graph
    redis_manager = request.app.state.redis_manager

    thread = thread_store.get_or_create_thread(thread_id, "segment")
    prior_messages = list(thread["messages"])
    thread_store.add_message(thread_id, {"role": "user", "content": query})

    # Register this run in Redis
    await redis_manager.start_run(thread_id, run_id)

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
                "validated_fields": [],
                "conditions_draft": [],
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
                            "op": "add",
                            "path": "/requirements",
                            "value": node_output["requirements"],
                        })
                    if "validated_fields" in node_output and node_output["validated_fields"]:
                        delta_ops.append({
                            "op": "add",
                            "path": "/validated_fields",
                            "value": node_output["validated_fields"],
                        })
                    if "conditions_draft" in node_output and node_output["conditions_draft"]:
                        delta_ops.append({
                            "op": "add",
                            "path": "/conditions_draft",
                            "value": node_output["conditions_draft"],
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
