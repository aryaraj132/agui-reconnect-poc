# Stream Reconnection Refinements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the reconnection POC with a unified two-phase reconnection API, 8-node pipeline (~80-100s), frontend tool call support (`update_progress_status`), Redis graceful degradation, and fast-forward UX during catch-up.

**Architecture:** The reconnect endpoint sends ThreadStore state first, then does a type-filtered catch-up from Redis (XRANGE), then follows live (XREAD BLOCK). The frontend `useRestoreThread` hook processes all three phases via SSE. A new `ProgressStatus` stepper component is driven by `useCopilotAction` + replayed `TOOL_CALL` events.

**Tech Stack:** Python/FastAPI, LangGraph, Redis Streams, React/Next.js, CopilotKit, Tailwind CSS

---

## File Structure

### Backend — Modified

| File | Responsibility |
|------|----------------|
| `src/stream_reconnection_demo/agent/segment/state.py` | Add state fields for 8 nodes |
| `src/stream_reconnection_demo/agent/segment/graph.py` | Expand to 8-node pipeline with 8-10s sleeps |
| `src/stream_reconnection_demo/agent/segment/routes.py` | Add TOOL_CALL emissions, update NODE_META for 8 nodes |
| `src/stream_reconnection_demo/core/redis_stream.py` | Add `read_existing()` and `follow_live()` methods |
| `src/stream_reconnection_demo/core/middleware.py` | Wrap Redis operations in try/except |
| `src/stream_reconnection_demo/api/reconnect.py` | Rewrite with two-phase logic + type filtering |
| `src/stream_reconnection_demo/main.py` | Wrap Redis init in try/except |

### Frontend — Modified

| File | Responsibility |
|------|----------------|
| `frontend/hooks/useRestoreThread.ts` | Add TOOL_CALL processing, catch-up vs live phases, fast-forward delay |
| `frontend/components/ReconnectionBanner.tsx` | Show phase labels (catching up / following live) |
| `frontend/app/segment/page.tsx` | Add `useCopilotAction` for `update_progress_status`, render `ProgressStatus` |

### Frontend — New

| File | Responsibility |
|------|----------------|
| `frontend/components/ProgressStatus.tsx` | Horizontal stepper showing 8 node states |

---

## Task 1: Expand State for 8 Nodes

**Files:**
- Modify: `src/stream_reconnection_demo/agent/segment/state.py`

- [ ] **Step 1: Update SegmentAgentState with new fields**

```python
from typing import TypedDict

from stream_reconnection_demo.schemas.segment import Segment


class SegmentAgentState(TypedDict):
    messages: list
    segment: Segment | None
    error: str | None
    # Multi-node pipeline tracking
    current_node: str
    requirements: str | None        # from analyze_requirements
    entities: list                   # from extract_entities
    validated_fields: list           # from validate_fields
    operator_mappings: list          # from map_operators
    conditions_draft: list           # from generate_conditions
    optimized_conditions: list       # from optimize_conditions
    scope_estimate: str | None       # from estimate_scope
```

- [ ] **Step 2: Verify import still works**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.agent.segment.state import SegmentAgentState; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/segment/state.py
git commit -m "feat: expand SegmentAgentState for 8-node pipeline"
```

---

## Task 2: Expand Graph to 8 Nodes

**Files:**
- Modify: `src/stream_reconnection_demo/agent/segment/graph.py`

- [ ] **Step 1: Add 4 new node functions**

Add these functions after the existing `analyze_requirements` function and before `_build_segment_node`:

```python
async def extract_entities(state: SegmentAgentState) -> dict:
    """Node 2: Identify entity types from the requirements."""
    await asyncio.sleep(8)

    requirements = state.get("requirements", "")
    entities = []

    # Extract entity categories from the requirements
    entity_categories = {
        "location": ["country", "city"],
        "temporal": ["signup_date", "last_purchase_date", "last_login_date"],
        "behavioral": ["purchase_count", "total_spent", "login_count", "page_views"],
        "demographic": ["age", "gender", "language"],
        "engagement": ["email_opened", "email_clicked", "app_opens", "feature_used"],
        "account": ["plan_type", "account_status"],
    }

    for category, fields in entity_categories.items():
        for field in fields:
            if field in requirements.lower():
                entities.append({"category": category, "field": field})

    if not entities:
        entities = [
            {"category": "location", "field": "country"},
            {"category": "behavioral", "field": "purchase_count"},
        ]

    return {
        "current_node": "extract_entities",
        "entities": entities,
    }


async def map_operators(state: SegmentAgentState) -> dict:
    """Node 4: Select appropriate operators for each validated field."""
    await asyncio.sleep(8)

    validated_fields = state.get("validated_fields", [])
    operator_mappings = []

    for field in validated_fields:
        if field in ("country", "city", "language", "gender", "plan_type", "account_status"):
            operator_mappings.append({
                "field": field,
                "operator": "equals",
                "type": "categorical",
            })
        elif field in ("signup_date", "last_purchase_date", "last_login_date"):
            operator_mappings.append({
                "field": field,
                "operator": "within_last",
                "type": "temporal",
            })
        elif field in ("purchase_count", "total_spent", "login_count",
                        "page_views", "session_duration", "age"):
            operator_mappings.append({
                "field": field,
                "operator": "greater_than",
                "type": "numeric",
            })
        else:
            operator_mappings.append({
                "field": field,
                "operator": "is_set",
                "type": "existence",
            })

    return {
        "current_node": "map_operators",
        "operator_mappings": operator_mappings,
    }


async def optimize_conditions(state: SegmentAgentState) -> dict:
    """Node 6: Simplify and deduplicate conditions."""
    await asyncio.sleep(10)

    conditions_draft = state.get("conditions_draft", [])
    seen_fields = set()
    optimized = []

    for cond in conditions_draft:
        field = cond.get("field", "")
        if field not in seen_fields:
            seen_fields.add(field)
            optimized.append({**cond, "optimized": True})

    return {
        "current_node": "optimize_conditions",
        "optimized_conditions": optimized,
    }


async def estimate_scope(state: SegmentAgentState) -> dict:
    """Node 7: Estimate audience size and reach."""
    await asyncio.sleep(8)

    optimized_conditions = state.get("optimized_conditions", [])
    num_conditions = len(optimized_conditions)

    if num_conditions <= 1:
        estimate = "Broad audience — minimal filtering applied"
    elif num_conditions <= 3:
        estimate = "Moderate audience — balanced between reach and specificity"
    else:
        estimate = "Narrow audience — highly targeted with multiple filters"

    return {
        "current_node": "estimate_scope",
        "scope_estimate": f"{estimate} ({num_conditions} conditions active)",
    }
```

- [ ] **Step 2: Update sleep durations for existing nodes**

Update `analyze_requirements`:
```python
async def analyze_requirements(state: SegmentAgentState) -> dict:
    """Node 1: Analyze the user's query and extract key requirements."""
    await asyncio.sleep(8)
    # ... rest stays the same
```

Update `validate_fields`:
```python
async def validate_fields(state: SegmentAgentState) -> dict:
    """Node 3: Validate detected fields against the available catalog."""
    await asyncio.sleep(8)
    # ... rest stays the same
```

Update `generate_conditions`:
```python
async def generate_conditions(state: SegmentAgentState) -> dict:
    """Node 5: Generate draft condition structures from validated fields."""
    await asyncio.sleep(10)
    # ... rest stays the same
```

- [ ] **Step 3: Update `generate_conditions` to use `operator_mappings`**

Replace the body of `generate_conditions` (after the sleep) with:

```python
    operator_mappings = state.get("operator_mappings", [])
    validated_fields = state.get("validated_fields", [])
    conditions_draft = []

    # Use operator_mappings if available, otherwise fall back to validated_fields
    if operator_mappings:
        for mapping in operator_mappings:
            conditions_draft.append({
                "field": mapping["field"],
                "operator": mapping["operator"],
                "value_hint": f"{mapping['type']} match",
            })
    else:
        for field in validated_fields:
            if field in ("country", "city", "language", "gender", "plan_type", "account_status"):
                conditions_draft.append({
                    "field": field, "operator": "equals", "value_hint": "exact match",
                })
            elif field in ("signup_date", "last_purchase_date", "last_login_date"):
                conditions_draft.append({
                    "field": field, "operator": "within_last", "value_hint": "temporal range",
                })
            elif field in ("purchase_count", "total_spent", "login_count",
                            "page_views", "session_duration", "age"):
                conditions_draft.append({
                    "field": field, "operator": "greater_than", "value_hint": "numeric threshold",
                })
            else:
                conditions_draft.append({
                    "field": field, "operator": "is_set", "value_hint": "existence check",
                })

    return {
        "current_node": "generate_conditions",
        "conditions_draft": conditions_draft,
    }
```

- [ ] **Step 4: Update `_build_segment_node` to use all context**

In the `build_segment` inner function, update the enriched prompt to include all node outputs:

```python
        requirements = state.get("requirements", "")
        entities = state.get("entities", [])
        validated_fields = state.get("validated_fields", [])
        operator_mappings = state.get("operator_mappings", [])
        conditions_draft = state.get("conditions_draft", [])
        optimized_conditions = state.get("optimized_conditions", [])
        scope_estimate = state.get("scope_estimate", "")

        enriched_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"## Pre-analyzed Context\n"
            f"Requirements: {requirements}\n"
            f"Entities: {entities}\n"
            f"Validated fields: {', '.join(validated_fields)}\n"
            f"Operator mappings: {operator_mappings}\n"
            f"Draft conditions: {conditions_draft}\n"
            f"Optimized conditions: {optimized_conditions}\n"
            f"Scope estimate: {scope_estimate}\n\n"
            f"Use these pre-analyzed results to generate the final segment."
        )
```

- [ ] **Step 5: Update `build_segment_graph` with 8-node pipeline**

```python
def build_segment_graph(model: str = "claude-sonnet-4-20250514"):
    """Build and compile the 8-node segment generation graph."""
    llm = ChatAnthropic(model=model)

    graph = StateGraph(SegmentAgentState)
    graph.add_node("analyze_requirements", analyze_requirements)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("validate_fields", validate_fields)
    graph.add_node("map_operators", map_operators)
    graph.add_node("generate_conditions", generate_conditions)
    graph.add_node("optimize_conditions", optimize_conditions)
    graph.add_node("estimate_scope", estimate_scope)
    graph.add_node("build_segment", _build_segment_node(llm))

    graph.add_edge(START, "analyze_requirements")
    graph.add_edge("analyze_requirements", "extract_entities")
    graph.add_edge("extract_entities", "validate_fields")
    graph.add_edge("validate_fields", "map_operators")
    graph.add_edge("map_operators", "generate_conditions")
    graph.add_edge("generate_conditions", "optimize_conditions")
    graph.add_edge("optimize_conditions", "estimate_scope")
    graph.add_edge("estimate_scope", "build_segment")
    graph.add_edge("build_segment", END)

    return graph.compile()
```

- [ ] **Step 6: Update graph_input in routes.py**

In `routes.py`, update the `graph_input` dict to include new state fields:

```python
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
```

- [ ] **Step 7: Verify graph builds**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.agent.segment.graph import build_segment_graph; g = build_segment_graph(); print(f'Nodes: {len(g.nodes)}'); print('OK')"`
Expected: `Nodes: 8` and `OK`

- [ ] **Step 8: Commit**

```bash
git add src/stream_reconnection_demo/agent/segment/graph.py src/stream_reconnection_demo/agent/segment/routes.py
git commit -m "feat: expand segment graph to 8 nodes with ~70s processing time"
```

---

## Task 3: Update NODE_META and Add TOOL_CALL Emissions

**Files:**
- Modify: `src/stream_reconnection_demo/agent/segment/routes.py`

- [ ] **Step 1: Replace NODE_META with 8-node metadata**

Replace the entire `NODE_META` dict:

```python
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
```

- [ ] **Step 2: Add TOOL_CALL emissions for `update_progress_status`**

In the `event_stream()` function inside `generate_segment`, add TOOL_CALL emissions right after each `STEP_STARTED` event. Find this block inside the `for node_name, node_output in chunk.items():` loop:

```python
                    meta = NODE_META[node_name]

                    # --- STEP START ---
                    yield emitter.emit_step_start(node_name)

                    # --- TOOL CALL: update_progress_status ---
                    import json as _json
                    tool_call_id = str(uuid.uuid4())
                    yield emitter.emit_tool_call_start(
                        tool_call_id, "update_progress_status", message_id
                    )
                    yield emitter.emit_tool_call_args(
                        tool_call_id,
                        _json.dumps({
                            "status": meta["status"],
                            "node": node_name,
                            "node_index": meta["index"],
                            "total_nodes": TOTAL_NODES,
                        }),
                    )
                    yield emitter.emit_tool_call_end(tool_call_id)
```

- [ ] **Step 3: Add STATE_DELTA ops for new node outputs**

In the same loop, update the `delta_ops` section to include new fields:

```python
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
```

- [ ] **Step 4: Add completion TOOL_CALL after final STATE_SNAPSHOT**

After the `yield emitter.emit_state_snapshot(segment_dict)` line, add:

```python
            # --- TOOL CALL: update_progress_status (completed) ---
            completion_tool_id = str(uuid.uuid4())
            yield emitter.emit_tool_call_start(
                completion_tool_id, "update_progress_status", message_id
            )
            yield emitter.emit_tool_call_args(
                completion_tool_id,
                _json.dumps({
                    "status": "completed",
                    "node": "build_segment",
                    "node_index": TOTAL_NODES - 1,
                    "total_nodes": TOTAL_NODES,
                }),
            )
            yield emitter.emit_tool_call_end(completion_tool_id)
```

- [ ] **Step 5: Move `import json` to top of file**

Add `import json` to the top-level imports and remove the inline `import json as _json`. Replace all `_json.dumps` with `json.dumps`.

- [ ] **Step 6: Verify server starts**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.agent.segment.routes import router; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/stream_reconnection_demo/agent/segment/routes.py
git commit -m "feat: add update_progress_status tool calls and 8-node metadata"
```

---

## Task 4: Add `read_existing()` and `follow_live()` to RedisStreamManager

**Files:**
- Modify: `src/stream_reconnection_demo/core/redis_stream.py`

- [ ] **Step 1: Add `read_existing()` method**

Add after the `mark_error` method:

```python
    async def read_existing(
        self, thread_id: str, run_id: str
    ) -> list[tuple[str, dict[str, str]]]:
        """XRANGE — return all existing entries (non-blocking).

        Returns list of (message_id, fields_dict) tuples.
        """
        key = self._stream_key(thread_id, run_id)
        entries = await self._redis.xrange(key)
        return entries  # list of (msg_id, {type, data, ts})

    async def follow_live(
        self,
        thread_id: str,
        run_id: str,
        last_id: str = "0",
    ) -> AsyncIterator[dict[str, Any]]:
        """XREAD BLOCK — yield new entries until STREAM_END.

        Starts reading from after ``last_id``. Blocks up to 2 seconds
        per read cycle. Stops when STREAM_END or STREAM_ERROR sentinel
        is encountered, or when the run is no longer active.
        """
        key = self._stream_key(thread_id, run_id)

        while True:
            entries = await self._redis.xread(
                {key: last_id}, block=2000, count=50
            )

            if entries:
                for _stream_name, messages in entries:
                    for msg_id, fields in messages:
                        last_id = msg_id
                        event_type = fields.get("type", "")

                        if event_type in (STREAM_END, STREAM_ERROR):
                            return

                        yield {
                            "id": msg_id,
                            "type": event_type,
                            "data": fields.get("data", ""),
                            "ts": fields.get("ts", ""),
                        }
            else:
                # No new entries within timeout — check if run is still active
                active = await self.get_active_run(thread_id)
                if active != run_id:
                    # Do one final non-blocking read
                    remaining = await self._redis.xread(
                        {key: last_id}, count=100
                    )
                    if remaining:
                        for _stream_name, messages in remaining:
                            for msg_id, fields in messages:
                                event_type = fields.get("type", "")
                                if event_type in (STREAM_END, STREAM_ERROR):
                                    return
                                yield {
                                    "id": msg_id,
                                    "type": event_type,
                                    "data": fields.get("data", ""),
                                    "ts": fields.get("ts", ""),
                                }
                    return

    async def stream_exists(self, thread_id: str, run_id: str) -> bool:
        """Check if a Redis stream exists for the given thread and run."""
        key = self._stream_key(thread_id, run_id)
        return await self._redis.exists(key) > 0
```

- [ ] **Step 2: Verify import**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.core.redis_stream import RedisStreamManager; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/core/redis_stream.py
git commit -m "feat: add read_existing, follow_live, stream_exists to RedisStreamManager"
```

---

## Task 5: Rewrite Reconnect Endpoint with Two-Phase Logic

**Files:**
- Modify: `src/stream_reconnection_demo/api/reconnect.py`

- [ ] **Step 1: Rewrite the reconnect endpoint**

Replace the entire file content:

```python
"""SSE reconnection endpoint with two-phase Redis reading.

Phase 0: Initial state from ThreadStore (MESSAGES_SNAPSHOT, STATE_SNAPSHOT)
Phase 1: Check Redis for stream data
Phase 2: Catch-up — XRANGE with type-based filtering
Phase 3: Live follow — XREAD BLOCK, unfiltered
"""

import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stream_reconnection_demo.core.events import EventEmitter
from stream_reconnection_demo.core.history import thread_store
from stream_reconnection_demo.core.middleware import _parse_sse_event

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)

# Event types to SKIP during catch-up (already sent from ThreadStore or would cause duplicates)
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

    Two-phase approach:
    1. Send ThreadStore state (messages + state snapshot)
    2. If Redis stream exists: catch-up with type filtering, then live follow
    """
    redis_manager = request.app.state.redis_manager

    async def replay_stream():
        # --- Phase 0: Initial State from ThreadStore ---
        thread = thread_store.get_thread(thread_id)
        if thread is None:
            yield emitter.emit_run_error("Thread not found")
            return

        synthetic_run_id = str(uuid.uuid4())
        yield emitter.emit_run_started(thread_id, synthetic_run_id)

        if thread["messages"]:
            yield emitter.emit_messages_snapshot(thread["messages"])

        if thread["state"]:
            yield emitter.emit_state_snapshot(thread["state"])

        # --- Phase 1: Check Redis ---
        run_id = None
        try:
            run_id = await redis_manager.get_active_run(thread_id)
        except Exception:
            logger.warning("Redis unavailable during reconnect, falling back to ThreadStore")
            yield emitter.emit_run_finished(thread_id, synthetic_run_id)
            return

        if run_id is None:
            # No active run — check if there's a completed stream we can replay
            # Look for any stream key matching this thread
            # Since we don't know the run_id, we check the thread's event history
            # If ThreadStore has state, we already sent it. Done.
            logger.info(
                "Reconnect: no active run for %s, sent state snapshot only",
                thread_id,
            )
            yield emitter.emit_run_finished(thread_id, synthetic_run_id)
            return

        # --- Phase 2: Catch-up (XRANGE, non-blocking) ---
        logger.info(
            "Reconnect: active run %s for %s, starting catch-up",
            run_id, thread_id,
        )

        last_id = "0"
        stream_ended = False

        try:
            entries = await redis_manager.read_existing(thread_id, run_id)
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

            # Type-based filtering: skip events that would duplicate ThreadStore data
            if event_type in CATCHUP_SKIP_TYPES:
                continue

            # Replay this event
            event_data = fields.get("data", "")
            if event_data:
                yield event_data

        if stream_ended:
            logger.info(
                "Reconnect: catch-up found STREAM_END for %s, run complete",
                thread_id,
            )
            yield emitter.emit_run_finished(thread_id, synthetic_run_id)
            return

        # --- Phase 3: Live follow (XREAD BLOCK, unfiltered) ---
        logger.info(
            "Reconnect: switching to live follow for %s from %s",
            thread_id, last_id,
        )

        try:
            async for entry in redis_manager.follow_live(thread_id, run_id, last_id):
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
```

- [ ] **Step 2: Verify import**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.api.reconnect import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/api/reconnect.py
git commit -m "feat: rewrite reconnect endpoint with two-phase Redis reading and type filtering"
```

---

## Task 6: Redis Graceful Degradation

**Files:**
- Modify: `src/stream_reconnection_demo/core/middleware.py`
- Modify: `src/stream_reconnection_demo/agent/segment/routes.py`
- Modify: `src/stream_reconnection_demo/main.py`

- [ ] **Step 1: Wrap RedisStreamMiddleware operations in try/except**

Replace the `RedisStreamMiddleware.apply` method in `middleware.py`:

```python
    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        try:
            async for event in event_stream:
                try:
                    await self._redis.write_event(
                        self._thread_id, self._run_id, event
                    )
                except Exception:
                    logger.warning("Redis write_event failed, skipping persistence")
                yield event
            try:
                await self._redis.mark_complete(self._thread_id, self._run_id)
            except Exception:
                logger.warning("Redis mark_complete failed")
        except Exception:
            try:
                await self._redis.mark_error(
                    self._thread_id, self._run_id, "Stream error"
                )
            except Exception:
                logger.warning("Redis mark_error failed")
            raise
```

- [ ] **Step 2: Wrap `start_run` in routes.py**

In `routes.py`, replace:
```python
    await redis_manager.start_run(thread_id, run_id)
```
with:
```python
    try:
        await redis_manager.start_run(thread_id, run_id)
    except Exception:
        logging.warning("Redis start_run failed, streaming without persistence")
```

- [ ] **Step 3: Wrap Redis init in main.py**

In `main.py`, replace the Redis initialization block:

```python
    # Initialize Redis connection
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    logger.info("Connecting to Redis at %s", redis_url)
    try:
        app.state.redis_manager = RedisStreamManager(redis_url)
        logger.info("Redis manager initialized")
    except Exception:
        logger.warning("Redis connection failed, running without persistence")
        app.state.redis_manager = RedisStreamManager(redis_url)  # lazy connect
```

And update the cleanup:

```python
    # Cleanup
    try:
        await app.state.redis_manager.close()
        logger.info("Redis connection closed")
    except Exception:
        logger.warning("Redis cleanup failed")
```

- [ ] **Step 4: Verify server starts**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/stream_reconnection_demo/core/middleware.py src/stream_reconnection_demo/agent/segment/routes.py src/stream_reconnection_demo/main.py
git commit -m "feat: add Redis graceful degradation with try/except wrapping"
```

---

## Task 7: Create ProgressStatus Frontend Component

**Files:**
- Create: `frontend/components/ProgressStatus.tsx`

- [ ] **Step 1: Create the ProgressStatus stepper component**

```typescript
"use client";

interface ProgressStatusProps {
  status: string;
  node: string;
  nodeIndex: number;
  totalNodes: number;
}

const NODE_LABELS: Record<string, string> = {
  analyze_requirements: "Analyze",
  extract_entities: "Entities",
  validate_fields: "Validate",
  map_operators: "Operators",
  generate_conditions: "Conditions",
  optimize_conditions: "Optimize",
  estimate_scope: "Scope",
  build_segment: "Build",
};

const NODE_ORDER = [
  "analyze_requirements",
  "extract_entities",
  "validate_fields",
  "map_operators",
  "generate_conditions",
  "optimize_conditions",
  "estimate_scope",
  "build_segment",
];

export function ProgressStatus({
  status,
  node,
  nodeIndex,
  totalNodes,
}: ProgressStatusProps) {
  const isCompleted = status === "completed";

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {isCompleted
            ? "Segment Complete"
            : `${NODE_LABELS[node] || node}...`}
        </span>
        <span className="text-xs text-gray-500">
          {isCompleted
            ? `${totalNodes}/${totalNodes}`
            : `${nodeIndex + 1}/${totalNodes}`}
        </span>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-1">
        {NODE_ORDER.slice(0, totalNodes).map((nodeName, i) => {
          let stepState: "completed" | "active" | "pending";
          if (isCompleted || i < nodeIndex) {
            stepState = "completed";
          } else if (i === nodeIndex) {
            stepState = "active";
          } else {
            stepState = "pending";
          }

          return (
            <div key={nodeName} className="flex-1 flex flex-col items-center">
              {/* Step indicator */}
              <div className="flex items-center w-full">
                {/* Line before */}
                {i > 0 && (
                  <div
                    className={`flex-1 h-0.5 ${
                      stepState === "pending"
                        ? "bg-gray-200 dark:bg-gray-700"
                        : "bg-green-500"
                    }`}
                  />
                )}

                {/* Circle */}
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
                    stepState === "completed"
                      ? "bg-green-500 text-white"
                      : stepState === "active"
                      ? "bg-blue-500 text-white"
                      : "bg-gray-200 dark:bg-gray-700 text-gray-400"
                  }`}
                >
                  {stepState === "completed" ? (
                    <svg
                      className="w-3.5 h-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={3}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  ) : stepState === "active" ? (
                    <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-gray-400" />
                  )}
                </div>

                {/* Line after */}
                {i < totalNodes - 1 && (
                  <div
                    className={`flex-1 h-0.5 ${
                      stepState === "completed" && i < nodeIndex
                        ? "bg-green-500"
                        : "bg-gray-200 dark:bg-gray-700"
                    }`}
                  />
                )}
              </div>

              {/* Label */}
              <span
                className={`text-[10px] mt-1 text-center leading-tight ${
                  stepState === "completed"
                    ? "text-green-600 dark:text-green-400"
                    : stepState === "active"
                    ? "text-blue-600 dark:text-blue-400 font-medium"
                    : "text-gray-400"
                }`}
              >
                {NODE_LABELS[nodeName] || nodeName}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds (component is created but not yet imported)

- [ ] **Step 3: Commit**

```bash
git add frontend/components/ProgressStatus.tsx
git commit -m "feat: add ProgressStatus stepper component for 8-node pipeline"
```

---

## Task 8: Add `useCopilotAction` and ProgressStatus to Segment Page

**Files:**
- Modify: `frontend/app/segment/page.tsx`

- [ ] **Step 1: Add imports and state**

Add to the imports at the top:

```typescript
import { useCopilotAction } from "@copilotkit/react-core";
```

(This import is added alongside the existing CopilotKit imports.)

Also add:

```typescript
import { ProgressStatus } from "@/components/ProgressStatus";
```

Add `useState` to the React import:

```typescript
import { Suspense, useEffect, useRef, useState } from "react";
```

- [ ] **Step 2: Add progress state and useCopilotAction to SegmentPageContent**

Inside `SegmentPageContent`, after the `useRestoreThread` call, add:

```typescript
  const [progressStatus, setProgressStatus] = useState<{
    status: string;
    node: string;
    nodeIndex: number;
    totalNodes: number;
  } | null>(null);

  useCopilotAction({
    name: "update_progress_status",
    parameters: [
      { name: "status", type: "string", description: "Current status" },
      { name: "node", type: "string", description: "Current node name" },
      { name: "node_index", type: "number", description: "Current node index" },
      { name: "total_nodes", type: "number", description: "Total number of nodes" },
    ],
    handler: ({ status, node, node_index, total_nodes }) => {
      setProgressStatus({
        status,
        node,
        nodeIndex: node_index,
        totalNodes: total_nodes,
      });
    },
  });
```

- [ ] **Step 3: Render ProgressStatus above SegmentCard**

Replace the `<main>` section in the return JSX:

```tsx
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-lg space-y-6">
          {progressStatus && (
            <ProgressStatus
              status={progressStatus.status}
              node={progressStatus.node}
              nodeIndex={progressStatus.nodeIndex}
              totalNodes={progressStatus.totalNodes}
            />
          )}
          {segment?.condition_groups ? (
            <SegmentCard segment={segment} />
          ) : isStreamActive && currentActivity ? (
            <div className="space-y-4">
              <ActivityIndicator
                activityType="processing"
                content={currentActivity}
              />
              {currentReasoning && (
                <ReasoningPanel reasoning={currentReasoning} defaultOpen />
              )}
            </div>
          ) : !progressStatus ? (
            <p className="text-sm text-gray-400 text-center">
              Describe your audience in the sidebar to generate a segment.
            </p>
          ) : null}
        </div>
      </main>
```

- [ ] **Step 4: Verify build**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/app/segment/page.tsx
git commit -m "feat: add useCopilotAction for update_progress_status and ProgressStatus rendering"
```

---

## Task 9: Update useRestoreThread with TOOL_CALL Processing and Fast-Forward

**Files:**
- Modify: `frontend/hooks/useRestoreThread.ts`

- [ ] **Step 1: Add TOOL_CALL event processing and catch-up detection**

In the `useRestoreThread` hook, add a new state variable after the existing state declarations:

```typescript
  const [isCatchingUp, setIsCatchingUp] = useState(false);
```

Update the `RestoreResult` interface to include it:

```typescript
interface RestoreResult {
  threadData: ThreadData | null;
  isRestoring: boolean;
  isStreamActive: boolean;
  isCatchingUp: boolean;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
  restoredSegment: Segment | null;
}
```

- [ ] **Step 2: Add TOOL_CALL handling in the event switch**

In the `reconnect` function's event switch statement, add cases for TOOL_CALL events and a CUSTOM event that signals the transition from catch-up to live:

```typescript
            case "TOOL_CALL_START":
            case "TOOL_CALL_ARGS":
            case "TOOL_CALL_END": {
              // Tool call events are processed by CopilotKit via the SSE stream.
              // During catch-up, they replay update_progress_status calls
              // which drive the ProgressStatus stepper.
              break;
            }

            case "STEP_STARTED":
            case "STEP_FINISHED": {
              // Step events are replayed during catch-up for progression visibility
              break;
            }
```

- [ ] **Step 3: Add fast-forward delay during catch-up**

The catch-up vs live distinction is determined by the backend sending events in two phases. The frontend needs to add a delay between catch-up events. Update the SSE processing loop:

Replace the `for await` loop with:

```typescript
        let catchingUp = true;
        setIsCatchingUp(true);

        for await (const event of parseSSEStream(reader)) {
          if (signal.aborted) break;

          const eventType = event.type as string;

          // Fast-forward delay during catch-up phase
          // (events from XRANGE come all at once, we add delay for visual progression)
          if (catchingUp && eventType !== "RUN_STARTED" && eventType !== "MESSAGES_SNAPSHOT" && eventType !== "STATE_SNAPSHOT" && eventType !== "RUN_FINISHED") {
            await new Promise((r) => setTimeout(r, 100));
          }

          switch (eventType) {
            // ... existing cases ...

            case "RUN_FINISHED":
            case "RUN_ERROR": {
              if (catchingUp) {
                // If we get RUN_FINISHED during what we thought was catch-up,
                // the run is actually complete — no live phase
                catchingUp = false;
                setIsCatchingUp(false);
              }
              setIsStreamActive(false);
              setTimeout(() => {
                setCurrentActivity(null);
                setCurrentReasoning("");
              }, 1000);
              break;
            }
          }
        }
```

Note: The transition from catch-up to live happens naturally — catch-up events come from XRANGE (fast), live events come from XREAD BLOCK (real-time gaps). The 100ms delay only applies during the burst of events that arrive quickly.

- [ ] **Step 4: Return `isCatchingUp` from the hook**

Update the return statement:

```typescript
  return {
    threadData,
    isRestoring,
    isStreamActive,
    isCatchingUp,
    currentActivity,
    currentReasoning,
    restoredSegment,
  };
```

And update the reset in the useEffect:

```typescript
    setIsCatchingUp(false);
```

- [ ] **Step 5: Verify build**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/hooks/useRestoreThread.ts
git commit -m "feat: add TOOL_CALL processing and fast-forward delay to useRestoreThread"
```

---

## Task 10: Update ReconnectionBanner with Phase Labels

**Files:**
- Modify: `frontend/components/ReconnectionBanner.tsx`
- Modify: `frontend/app/segment/page.tsx`

- [ ] **Step 1: Add `isCatchingUp` prop to ReconnectionBanner**

Update the interface and component:

```typescript
interface ReconnectionBannerProps {
  isRestoring: boolean;
  isStreamActive: boolean;
  isCatchingUp: boolean;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
}

export function ReconnectionBanner({
  isRestoring,
  isStreamActive,
  isCatchingUp,
  currentActivity,
  currentReasoning,
}: ReconnectionBannerProps) {
```

- [ ] **Step 2: Update status text to show phase**

Replace the status `<span>`:

```tsx
              <span className="text-sm font-medium truncate">
                {isStreamActive
                  ? isCatchingUp
                    ? "Catching up..."
                    : currentActivity?.title || "Following live stream..."
                  : "Restoring session..."}
              </span>
```

- [ ] **Step 3: Update segment page to pass `isCatchingUp`**

In `page.tsx`, destructure `isCatchingUp` from the `useRestoreThread` hook:

```typescript
  const {
    threadData,
    isRestoring,
    isStreamActive,
    isCatchingUp,
    currentActivity,
    currentReasoning,
    restoredSegment,
  } = useRestoreThread(threadId, isExistingThread);
```

And pass it to the banner:

```tsx
      <ReconnectionBanner
        isRestoring={isRestoring}
        isStreamActive={isStreamActive}
        isCatchingUp={isCatchingUp}
        currentActivity={currentActivity}
        currentReasoning={currentReasoning}
      />
```

- [ ] **Step 4: Verify build**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/components/ReconnectionBanner.tsx frontend/app/segment/page.tsx
git commit -m "feat: add phase labels to ReconnectionBanner (catching up / following live)"
```

---

## Task 11: Integration Verification

- [ ] **Step 1: Start Redis**

Run: `just redis` (in a separate terminal)

- [ ] **Step 2: Start backend**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -m stream_reconnection_demo.main`

- [ ] **Step 3: Start frontend**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npm run dev`

- [ ] **Step 4: Test normal flow**

1. Go to `http://localhost:3000/segment`
2. Type a query like "Users from the US who signed up in the last 30 days and made a purchase"
3. Verify: 8 nodes process with activity indicator + reasoning in sidebar
4. Verify: ProgressStatus stepper appears and advances through all 8 nodes
5. Verify: Final SegmentCard appears with conditions

- [ ] **Step 5: Test reconnection (active run)**

1. Start a generation
2. At ~30s (node 3-4), reload the browser
3. Verify: ReconnectionBanner shows "Catching up..." with fast-forward
4. Verify: ProgressStatus stepper catches up quickly through completed nodes
5. Verify: Banner transitions to "Following live stream..."
6. Verify: Remaining nodes process in real-time
7. Verify: Final SegmentCard appears

- [ ] **Step 6: Test reconnection (completed run)**

1. Complete a full generation
2. Reload the browser
3. Verify: SegmentCard restores immediately with completed stepper

- [ ] **Step 7: Test Redis down**

1. Stop Redis (`podman stop redis-reconnect`)
2. Start a new generation
3. Verify: Generation works (warnings in backend logs)
4. Verify: Reload falls back to ThreadStore state restoration

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "docs: add implementation plan for stream reconnection refinements"
```
