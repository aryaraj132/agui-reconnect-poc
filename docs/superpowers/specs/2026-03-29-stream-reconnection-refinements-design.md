# Stream Reconnection POC — Refinements Design

## Context

The initial POC implementation streams AG-UI events from a multi-node LangGraph segment agent through Redis Streams. When a user reloads, a reconnect endpoint replays events from Redis. This refinement addresses:

1. **Unified reconnection API** — merge initial state fetch and Redis stream replay into one SSE endpoint
2. **Event deduplication** — catch-up vs live phase with type-based filtering to prevent duplicate messages/state
3. **Frontend tool calls** — add `update_progress_status` tool to demonstrate TOOL_CALL replay during reconnection
4. **More nodes** — expand to 8 nodes (~70s of simulated processing + LLM call) for proper testing
5. **Redis graceful degradation** — fail silently if Redis is unavailable
6. **Fast-forward UX** — catch-up events replayed with ~100ms delay for visual progression

---

## 1. Unified Reconnection Endpoint

### Current behavior
- `useRestoreThread` hook connects to `GET /api/v1/reconnect/{thread_id}`
- The endpoint replays ALL events from Redis or returns ThreadStore state

### New behavior
Single SSE endpoint with two-phase Redis reading:

```
GET /api/v1/reconnect/{thread_id}

Phase 0 — Initial State:
  1. RUN_STARTED
  2. MESSAGES_SNAPSHOT (from ThreadStore — all messages)
  3. STATE_SNAPSHOT (from ThreadStore — latest agent state)

Phase 1 — Check Redis:
  4a. If no active run in Redis AND no Redis stream exists → RUN_FINISHED → done
  4b. If no active run BUT Redis stream exists (completed run, stream not expired)
      → Continue to Phase 2 (catch-up only, no live follow)
  4c. If active run in Redis → Continue to Phase 2 + Phase 3

Phase 2 — Catch-up (XRANGE, non-blocking):
  Read ALL existing entries from Redis stream.
  For each entry:
    Skip if type in: MESSAGES_SNAPSHOT, STATE_SNAPSHOT, STATE_DELTA,
                      TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT, TEXT_MESSAGE_END,
                      RUN_STARTED, RUN_FINISHED
    Replay if type in: STEP_STARTED, STEP_FINISHED,
                        ACTIVITY_SNAPSHOT,
                        REASONING_START, REASONING_MESSAGE_START, REASONING_MESSAGE_CONTENT,
                        REASONING_MESSAGE_END, REASONING_END,
                        TOOL_CALL_START, TOOL_CALL_ARGS, TOOL_CALL_END,
                        CUSTOM

  If STREAM_END sentinel found during catch-up → RUN_FINISHED → done

Phase 3 — Live follow (XREAD BLOCK, only if run is active):
  Read new events as they arrive.
  NO FILTERING — all event types pass through.
  Stop when STREAM_END sentinel received.

Final:
  RUN_FINISHED
```

### Files modified
- `src/stream_reconnection_demo/api/reconnect.py` — rewrite with two-phase logic
- `src/stream_reconnection_demo/core/redis_stream.py` — add `read_existing()` and `follow_live()` methods

### RedisStreamManager API changes

```python
async def read_existing(self, thread_id, run_id) -> list[tuple[str, dict]]:
    """XRANGE — return all existing entries (non-blocking)."""

async def follow_live(self, thread_id, run_id, last_id) -> AsyncIterator[dict]:
    """XREAD BLOCK — yield new entries until STREAM_END."""
```

The existing `read_events()` method is replaced by the combination of these two.

---

## 2. 8-Node Segment Pipeline

### Node definitions

| # | Node | Sleep | Progress | Status | Description |
|---|------|-------|----------|--------|-------------|
| 1 | `analyze_requirements` | 8s | 0.10 | `analyzing` | Parse query, extract segmentation intent |
| 2 | `extract_entities` | 8s | 0.20 | `extracting` | Identify entity types (locations, behaviors, etc.) |
| 3 | `validate_fields` | 8s | 0.30 | `validating` | Check entities against available field catalog |
| 4 | `map_operators` | 8s | 0.45 | `mapping` | Select appropriate operators for each field |
| 5 | `generate_conditions` | 10s | 0.55 | `generating` | Build draft condition structures |
| 6 | `optimize_conditions` | 10s | 0.70 | `optimizing` | Simplify and deduplicate conditions |
| 7 | `estimate_scope` | 8s | 0.85 | `estimating` | Estimate audience size and reach |
| 8 | `build_segment` | LLM | 0.95 | `building` | Final LLM call with structured output |

Total simulated time: ~70s + LLM call ≈ 80-100 seconds.

After `build_segment` completes: status → `completed`, progress → 1.0.

### Files modified
- `src/stream_reconnection_demo/agent/segment/graph.py` — add 4 new nodes
- `src/stream_reconnection_demo/agent/segment/state.py` — add state fields for new nodes
- `src/stream_reconnection_demo/agent/segment/routes.py` — update NODE_META with all 8 nodes

### State extensions

```python
class SegmentAgentState(TypedDict):
    messages: list
    segment: Segment | None
    error: str | None
    current_node: str
    requirements: str | None        # from analyze_requirements
    entities: list                   # from extract_entities
    validated_fields: list           # from validate_fields
    operator_mappings: list          # from map_operators
    conditions_draft: list           # from generate_conditions
    optimized_conditions: list       # from optimize_conditions
    scope_estimate: str | None       # from estimate_scope
```

---

## 3. Frontend Tool — update_progress_status

### Backend emission

At each node transition, emit:
```
TOOL_CALL_START(tool_call_id, "update_progress_status", parent_message_id)
TOOL_CALL_ARGS(tool_call_id, {"status": "analyzing", "node": "analyze_requirements", "node_index": 0, "total_nodes": 8})
TOOL_CALL_END(tool_call_id)
```

After final STATE_SNAPSHOT:
```
TOOL_CALL_START/ARGS({"status": "completed", ...})/END
```

### Frontend handling

**`useCopilotAction`** in the segment page registers the `update_progress_status` action:
```typescript
useCopilotAction({
  name: "update_progress_status",
  parameters: [
    { name: "status", type: "string" },
    { name: "node", type: "string" },
    { name: "node_index", type: "number" },
    { name: "total_nodes", type: "number" },
  ],
  handler: ({ status, node, node_index, total_nodes }) => {
    setProgressStatus({ status, node, nodeIndex: node_index, totalNodes: total_nodes });
  },
});
```

**`ProgressStatus.tsx`** component renders above SegmentCard:
- Horizontal stepper showing 8 nodes
- Completed nodes: green checkmark
- Current node: blue spinner
- Pending nodes: gray circle
- Status text showing current node name

### Reconnection behavior
During catch-up, TOOL_CALL events are replayed with ~100ms fast-forward delay. The `update_progress_status` handler fires for each → the stepper animates through completed nodes quickly.

### Files
- `frontend/components/ProgressStatus.tsx` — new component
- `frontend/app/segment/page.tsx` — add useCopilotAction + ProgressStatus rendering
- `src/stream_reconnection_demo/agent/segment/routes.py` — add TOOL_CALL emissions

---

## 4. Redis Graceful Degradation

### Approach
Wrap ALL Redis operations in try/except. On failure, log a warning and continue.

### RedisStreamMiddleware changes
```python
async def apply(self, event_stream):
    try:
        async for event in event_stream:
            try:
                await self._redis.write_event(...)
            except Exception:
                logger.warning("Redis write failed, skipping")
            yield event
        try:
            await self._redis.mark_complete(...)
        except Exception:
            logger.warning("Redis mark_complete failed")
    except Exception:
        # If Redis middleware itself fails, still yield events
        raise
```

### Route handler changes
```python
try:
    await redis_manager.start_run(thread_id, run_id)
except Exception:
    logger.warning("Redis start_run failed, streaming without persistence")
```

### Reconnect endpoint
If Redis is unavailable, fall back to ThreadStore-only state restoration (Phase 0 → RUN_FINISHED).

### Files modified
- `src/stream_reconnection_demo/core/middleware.py`
- `src/stream_reconnection_demo/agent/segment/routes.py`
- `src/stream_reconnection_demo/api/reconnect.py`

---

## 5. Frontend Reconnection UX

### Fast-forward timing
- Catch-up events: ~100ms delay between each replayed event
- Live events: no artificial delay, real-time
- Detection: the `useRestoreThread` hook tracks whether events are from catch-up (batch read) or live (streaming)

### useRestoreThread changes
- Process TOOL_CALL events: extract `update_progress_status` args, update progress state
- Add `isCatchingUp` state to distinguish catch-up from live phase
- During catch-up: 100ms delay between events via `await new Promise(r => setTimeout(r, 100))`
- During live: immediate processing

### ReconnectionBanner improvements
- Show "Catching up..." during catch-up phase
- Show "Following live stream..." during live phase
- Show node progress from tool call data

### Files modified
- `frontend/hooks/useRestoreThread.ts`
- `frontend/components/ReconnectionBanner.tsx`
- `frontend/app/segment/page.tsx`

---

## 6. Event Flow Summary

### Normal flow (no reload)
```
POST /api/v1/segment
  → RUN_STARTED
  → MESSAGES_SNAPSHOT
  → [Per node ×8]:
      STEP_STARTED → TOOL_CALL(update_progress_status) → ACTIVITY_SNAPSHOT → REASONING_* → STATE_DELTA → STEP_FINISHED
  → TOOL_CALL(status:completed)
  → ACTIVITY_SNAPSHOT(100%)
  → STATE_SNAPSHOT (final segment)
  → TEXT_MESSAGE_START/CONTENT/END
  → RUN_FINISHED

  Each event: written to Redis BEFORE yielding to client
```

### Reconnection flow (after reload)
```
GET /api/v1/reconnect/{thread_id}

  Phase 0 (instant):
    → RUN_STARTED
    → MESSAGES_SNAPSHOT (ThreadStore)
    → STATE_SNAPSHOT (ThreadStore)

  Phase 1 (catch-up, fast-forward ~100ms/event):
    → Replay: STEP_*, ACTIVITY_*, REASONING_*, TOOL_CALL_*, CUSTOM
    → Skip: MESSAGES_*, STATE_*, TEXT_MESSAGE_*, RUN_*

  Phase 2 (live, real-time):
    → ALL events unfiltered
    → Until STREAM_END sentinel

  Final:
    → RUN_FINISHED
```

---

## Verification

1. **Normal flow**: Start generation, watch 8 nodes process with stepper + activity + reasoning in sidebar
2. **Reconnection (active)**: Start generation, reload at ~30s, see ReconnectionBanner with fast-forward, then live follow, then segment card
3. **Reconnection (completed)**: Complete full generation, reload, instant restore with completed stepper
4. **Redis down**: Stop Redis, start generation — works without persistence. Reconnect falls back to ThreadStore.
5. **Tool call replay**: Reload mid-stream, verify stepper component catches up correctly via TOOL_CALL replay
