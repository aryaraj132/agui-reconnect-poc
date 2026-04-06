# Integration Plan: ag-ui-langgraph + Custom Reconnection

## Context

The project manually emits every AG-UI event (~170 lines in `run_segment_pipeline()`) by iterating over `graph.astream(stream_mode="updates")` and calling `EventEmitter` methods for each step. The `ag-ui-langgraph` library automates this by wrapping `graph.astream_events()` and translating LangGraph internals into AG-UI events automatically — but it has zero reconnection support.

**Goal**: Replace the manual event translation with `LangGraphAgent.run()` while keeping the Redis Pub/Sub reconnection infrastructure. The `EventAdapter` bridges the two: it consumes AG-UI event objects from the library, translates custom events from graph nodes, encodes everything to SSE strings, and feeds them into the existing `agent_runner` → Redis pipeline.

**What changes**: Event generation layer. **What stays**: Redis pubsub, agent_runner, reconnection handlers, frontend.

## Architecture

```
Graph Nodes (adispatch_custom_event for progress/activity/reasoning)
     │
     v
LangGraphAgent.run()      ← auto: RUN_*, STEP_*, STATE_SNAPSHOT, MESSAGES_SNAPSHOT, TEXT_MESSAGE_*, REASONING_* (LLM)
     │
     v
EventAdapter               ← translates custom events → proper AG-UI types, encodes to SSE strings
     │
     v
agent_runner               ← publishes SSE strings to Redis (unchanged)
     │
     v
pubsub catch_up_and_follow ← streams to client (unchanged)
```

## Implementation Steps

### Step 1: Add dependency

**File**: `pyproject.toml`

Add `"ag-ui-langgraph>=0.0.29"` to dependencies.

---

### Step 2: Define graph output schema + add `config` param to nodes + emit custom events

**File**: `src/stream_reconnection_demo/agent/segment/state.py`

Add a narrow output schema so the library's STATE_SNAPSHOT only contains the `segment` field (not the full internal state):

```python
class SegmentOutput(TypedDict):
    segment: Segment | None
```

**File**: `src/stream_reconnection_demo/agent/segment/graph.py`

**2a. Use output schema**: Change `StateGraph(SegmentAgentState)` → `StateGraph(SegmentAgentState, output=SegmentOutput)`. This makes the library's `get_state_snapshot()` only include `segment` in STATE_SNAPSHOT events — matching the current behavior where only the final segment data reaches the frontend via STATE_SNAPSHOT.

**2b. Add config param + custom events**: Currently nodes have signature `async def analyze_requirements(state: SegmentAgentState) -> dict`. LangGraph auto-injects `config` if the function signature accepts it — needed for `adispatch_custom_event`.

Move `NODE_META` from `routes.py` into `graph.py` (it's graph-level metadata). Each simulated node gets custom event dispatches:

```python
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.runnables import RunnableConfig

async def analyze_requirements(state: SegmentAgentState, config: RunnableConfig) -> dict:
    # Progress
    await adispatch_custom_event("progress_update", {
        "status": "analyzing", "node": "analyze_requirements",
        "node_index": 0, "total_nodes": 8,
    }, config=config)
    
    # Activity
    await adispatch_custom_event("activity_snapshot", {
        "title": "Analyzing Requirements", "progress": 0.10,
        "details": "Parsing user query...",
    }, config=config)
    
    # Simulated reasoning
    await adispatch_custom_event("node_reasoning", {
        "steps": ["Parsing the natural language query...", "Identifying target audience...", "Mapping keywords..."],
    }, config=config)
    
    await asyncio.sleep(8)
    # ... existing logic unchanged ...
    return {"current_node": "analyze_requirements", "requirements": requirements}
```

The `build_segment` node (LLM-calling) does NOT need reasoning custom events — the library auto-detects reasoning from `ChatAnthropic` stream. It only needs the progress_update + activity_snapshot custom events.

**7 simulated nodes**: Add `config: RunnableConfig` param + 3 custom event dispatches each.
**`build_segment` closure**: Add `config: RunnableConfig` param + 2 custom event dispatches (progress + activity).

---

### Step 3: Create `core/event_adapter.py`

**New file**: `src/stream_reconnection_demo/core/event_adapter.py`

Bridges `LangGraphAgent.run()` output to SSE strings, translating custom events into proper AG-UI event types.

Key responsibilities:
1. Clone agent per-request, call `agent.run(input_data)`
2. Intercept `EventType.CUSTOM` events and translate:
   - `"progress_update"` → `ToolCallStartEvent` + `ToolCallArgsEvent` + `ToolCallEndEvent`
   - `"activity_snapshot"` → `ActivitySnapshotEvent`
   - `"node_reasoning"` → `ReasoningStartEvent` + `ReasoningMessageStartEvent` + `ReasoningMessageContentEvent` (per step) + `ReasoningMessageEndEvent` + `ReasoningEndEvent`
   - `"state_delta"` → `StateDeltaEvent` with JSON Patch ops (emitted from nodes for intermediate field updates)
   - `"manually_emit_*"` events → already handled by library (suppress the duplicate CUSTOM echo)
3. Intercept `EventType.STATE_SNAPSHOT` events and apply filtering:
   - The graph output schema (`SegmentOutput`) limits snapshots to `{segment: ...}` by default
   - The adapter applies additional fine-tuning: suppress intermediate `{segment: null}` snapshots (no value yet), pass through final snapshot with segment data
4. After `RUN_STARTED`: inject empty `StateSnapshotEvent({})` + reset progress tool call (matches current behavior)
5. Before `RUN_FINISHED`: inject completion progress tool call + 100% activity snapshot
6. Encode each event via `EventEncoder.encode()` → yields SSE strings

```python
class EventAdapter:
    def __init__(self):
        self._encoder = EventEncoder()

    async def stream_events(self, agent: LangGraphAgent, input_data: RunAgentInput) -> AsyncIterator[str]:
        request_agent = agent.clone()
        async for event_obj in request_agent.run(input_data):
            # Intercept CUSTOM events for translation
            if event_obj.type == EventType.CUSTOM:
                async for translated in self._translate_custom(event_obj):
                    yield self._encoder.encode(translated)
                continue
            
            # Filter STATE_SNAPSHOT: suppress intermediate {segment: null} snapshots
            # The graph output schema limits to segment-only, but intermediate
            # node exits produce {segment: None} which is noise. Only pass through
            # snapshots where segment has actual data (the final one).
            if event_obj.type == EventType.STATE_SNAPSHOT:
                snapshot = event_obj.snapshot or {}
                if snapshot.get("segment") is None:
                    continue  # suppress intermediate empty snapshot
                # Final snapshot with segment data — pass through
            
            # Inject state clearing after RUN_STARTED
            if event_obj.type == EventType.RUN_STARTED:
                yield self._encoder.encode(event_obj)
                yield self._encoder.encode(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot={}))
                # ... reset progress tool call ...
                continue
            
            yield self._encoder.encode(event_obj)
    
    async def _translate_custom(self, event_obj):
        name = event_obj.name
        data = event_obj.value
        
        if name == "progress_update":
            tool_call_id = str(uuid.uuid4())
            yield ToolCallStartEvent(...)
            yield ToolCallArgsEvent(tool_call_id=tool_call_id, delta=json.dumps(data))
            yield ToolCallEndEvent(...)
        
        elif name == "activity_snapshot":
            yield ActivitySnapshotEvent(...)
        
        elif name == "node_reasoning":
            reasoning_id = str(uuid.uuid4())
            yield ReasoningStartEvent(...)
            yield ReasoningMessageStartEvent(...)
            for step in data["steps"]:
                yield ReasoningMessageContentEvent(message_id=reasoning_id, delta=step)
                await asyncio.sleep(0.05)
            yield ReasoningMessageEndEvent(...)
            yield ReasoningEndEvent(...)
        
        elif name == "state_delta":
            # Nodes emit intermediate field updates as STATE_DELTA
            yield StateDeltaEvent(type=EventType.STATE_DELTA, delta=data["ops"])
```

**Intermediate state deltas**: Graph nodes emit `adispatch_custom_event("state_delta", {"ops": [{op: "add", path: "/requirements", value: ...}]})` after computing their output. The adapter translates these into `StateDeltaEvent`, preserving the current behavior where the frontend receives incremental field updates for intermediate pipeline results.

Interface: `stream_events()` → `AsyncIterator[str]` (SSE strings) — **same interface as current `run_segment_pipeline()`**, so `agent_runner` needs zero changes.

---

### Step 4: Initialize `LangGraphAgent` in app lifespan

**File**: `src/stream_reconnection_demo/main.py`

```python
from ag_ui_langgraph import LangGraphAgent

# In lifespan:
segment_graph = build_segment_graph(checkpointer=checkpointer)
app.state.segment_graph = segment_graph  # keep for reconnection handlers
app.state.segment_agent = LangGraphAgent(name="segment", graph=segment_graph)

stateful_graph = build_segment_graph(checkpointer=stateful_checkpointer)
app.state.stateful_segment_graph = stateful_graph
app.state.stateful_agent = LangGraphAgent(name="stateful-segment", graph=stateful_graph)
```

Both raw graph (for checkpointer reads in `_handle_connect`) and `LangGraphAgent` wrapper are stored.

---

### Step 5: Refactor `_handle_chat` in segment routes

**File**: `src/stream_reconnection_demo/agent/segment/routes.py`

**Remove**: `run_segment_pipeline()` (~170 lines), `NODE_META` dict (moved to graph.py), `_DELTA_FIELDS` list.

**Change `_handle_chat()`**: Replace pipeline creation with EventAdapter:

```python
from ag_ui.core import RunAgentInput, UserMessage
from stream_reconnection_demo.core.event_adapter import EventAdapter

async def _handle_chat(pubsub, segment_graph, segment_agent, thread_id, run_id, query):
    # ... duplicate check stays exactly as-is ...
    
    await pubsub.start_run(thread_id, run_id)
    
    input_data = RunAgentInput(
        thread_id=thread_id,
        run_id=run_id,
        messages=[UserMessage(id=str(uuid.uuid4()), role="user", content=query)],
        state={},
        tools=[],
        context=[],
        forwarded_props={},
    )
    
    adapter = EventAdapter()
    event_stream = adapter.stream_events(segment_agent, input_data)
    start_agent_task(pubsub, segment_graph, thread_id, run_id, event_stream)
    
    await asyncio.sleep(0.1)
    return StreamingResponse(pubsub.catch_up_and_follow(thread_id, run_id), ...)
```

**Update endpoint** to pass `segment_agent` from `request.app.state.segment_agent`.

**Keep unchanged**: `_handle_connect()`, `get_segment_state()`, `generate_segment()` endpoint structure, duplicate query prevention logic.

---

### Step 6: Refactor stateful-segment routes (same pattern)

**File**: `src/stream_reconnection_demo/agent/stateful_segment/routes.py`

Same transformation: remove `run_stateful_segment_pipeline()`, use `EventAdapter` + `LangGraphAgent` in `_handle_stateful_chat()`.

**Keep unchanged**: `_handle_stateful_connect()`, `_emit_synthetic_catchup()`, `_reconstruct_progress_from_state()`.

---

### Step 7: Keep `events.py` for reconnection use

**File**: `src/stream_reconnection_demo/core/events.py`

No removals. `EventEmitter` is still used by:
- `_handle_connect()` — emit RUN_STARTED/FINISHED for empty runs, STATE_SNAPSHOT for checkpoint replay
- `_handle_chat()` — emit the "already done" minimal run for duplicate queries
- `_emit_synthetic_catchup()` — reconstruct events from checkpointer state

Usage just shifts: no longer called by the pipeline path, only by reconnection/replay handlers.

---

## Files Summary

| File | Action | What changes |
|------|--------|-------------|
| `pyproject.toml` | Edit | Add `ag-ui-langgraph>=0.0.29` |
| `agent/segment/state.py` | Edit | Add `SegmentOutput` TypedDict for graph output schema |
| `agent/segment/graph.py` | Edit | Use `SegmentOutput` output schema, add `config` param to nodes, add `NODE_META`, add `adispatch_custom_event` calls (progress, activity, reasoning, state_delta) |
| `core/event_adapter.py` | **New** | EventAdapter class bridging LangGraphAgent → SSE strings |
| `main.py` | Edit | Create `LangGraphAgent` instances, store in `app.state` |
| `agent/segment/routes.py` | Edit | Remove `run_segment_pipeline` + `NODE_META` + `_DELTA_FIELDS`, use EventAdapter in `_handle_chat` |
| `agent/stateful_segment/routes.py` | Edit | Remove `run_stateful_segment_pipeline` + `NODE_META`, use EventAdapter in `_handle_stateful_chat` |
| `core/events.py` | Unchanged | Still used by reconnection handlers |
| `core/pubsub.py` | Unchanged | Reconnection infrastructure |
| `core/agent_runner.py` | Unchanged | Consumes `AsyncIterator[str]` — same interface |
| Frontend | Unchanged | Same AG-UI events reaching CopilotKit |

## Key Design Decisions

1. **Custom event names** (`progress_update`, `activity_snapshot`, `node_reasoning`, `state_delta`) instead of `manually_emit_*` — avoids the duplicate CUSTOM event echo that `manually_emit_*` produces (the library emits both the translated event AND a CUSTOM event for those names).

2. **EventAdapter as the seam** — keeps `agent_runner` unchanged (same `AsyncIterator[str]` interface), keeps reconnection handlers unchanged, isolates all library interaction to one new module.

3. **Two-layer state filtering** — Graph output schema (`SegmentOutput`) limits the library's STATE_SNAPSHOT to only the `segment` field (not messages, entities, etc.). The EventAdapter adds fine-tuning: suppresses intermediate `{segment: null}` snapshots, passes through the final snapshot with actual segment data. This matches current behavior exactly.

4. **STATE_DELTA preserved for intermediate fields** — Nodes emit `state_delta` custom events with JSON Patch ops for intermediate field updates (requirements, entities, etc.). The EventAdapter translates these into proper `StateDeltaEvent` events, matching the current frontend behavior where `useCoAgent` receives incremental state updates during pipeline execution.

## Verification

1. `uv sync` — ensure dependency resolves
2. Start Redis + backend + frontend
3. **Test new run**: Send a segment query → verify 8-step progress stepper, reasoning panels, final segment card
4. **Test reconnection (Strategy 1)**: Reload browser mid-execution → verify catch-up from Redis List, progress restoration, pipeline completion
5. **Test reconnection (Strategy 2)**: Same test on `/stateful-segment` → verify synthetic catch-up from checkpointer
6. **Test duplicate prevention**: After run completes, verify CopilotKit re-send returns minimal run with segment state preserved
7. **Test empty connect**: Load page with no prior thread → verify empty run (RUN_STARTED + RUN_FINISHED)
