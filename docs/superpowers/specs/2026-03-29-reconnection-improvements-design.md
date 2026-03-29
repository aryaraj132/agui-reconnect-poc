# Reconnection Improvements Design

## Context

The stream reconnection demo now uses a plain React + webpack frontend that communicates directly with the Python backend via SSE (no CopilotKit proxy). The current reconnect endpoint (`GET /api/v1/reconnect/{thread_id}`) handles basic catch-up from Redis but has gaps:

- **Mid-stream reliability**: Fast-forward replay works but lacks polish (no configurable delay, no transition states)
- **Backend crash recovery**: If the backend restarts during generation, the reconnect endpoint finds a stale `active_run` key with no new events — currently it hangs on XREAD BLOCK indefinitely
- **Multi-tab**: No special handling — tabs may trigger duplicate generations via POST
- **Multi-turn**: Only the latest run is tracked; follow-up messages need per-run Redis storage and sequential replay
- **UX**: ReconnectionBanner exists but doesn't distinguish between catch-up, live follow, stale recovery, or completion

This design addresses all of these as a cohesive system.

## Architecture: Unified Reconnect Endpoint

Single endpoint handles all reconnection scenarios via state detection:

```
GET /api/v1/reconnect/{thread_id}
│
├─ ThreadStore has state? → Emit MESSAGES_SNAPSHOT + STATE_SNAPSHOT
│
├─ Redis lookup:
│   ├─ Active run (stream receiving events) → ACTIVE PATH
│   ├─ Completed stream (STREAM_END found)  → COMPLETED PATH
│   ├─ Stale run (active key but no events for >30s) → STALE PATH
│   ├─ No data → EMPTY PATH (error)
│   └─ Redis unavailable → DEGRADED PATH (ThreadStore fallback)
```

### Path Details

**ACTIVE PATH** — mid-stream reload:
1. Phase 1: XRANGE catch-up with configurable fast-forward delay (200ms per event)
2. Phase 2: XREAD BLOCK live follow (unfiltered, real-time)
3. On STREAM_END sentinel → emit RUN_FINISHED

**COMPLETED PATH** — post-completion reload:
1. XRANGE full replay with fast-forward delay
2. Emit RUN_FINISHED

**STALE PATH** — backend crashed mid-generation:
1. XRANGE replay of partial events (fast-forward)
2. Emit CUSTOM event `{ name: "run_stale", value: { reason: "no_heartbeat" } }`
3. Clear stale `active_run` key in Redis
4. Extract last user query from ThreadStore or Redis events
5. Internally POST to `/api/v1/segment` to restart pipeline
6. Forward events from new run through same SSE connection

**EMPTY PATH** — no data anywhere:
1. Emit RUN_ERROR "Thread not found"

**DEGRADED PATH** — Redis unavailable:
1. If ThreadStore has state → emit it + RUN_FINISHED
2. Otherwise → RUN_ERROR

## Stale Run Detection

A run is "stale" when:
- `active_run:{thread_id}` key exists in Redis
- The stream (`stream:{thread_id}:{run_id}`) has entries
- The most recent entry timestamp is older than `STALE_TIMEOUT` (30 seconds)

Detection method: after XRANGE, check the timestamp of the last entry. If `now - last_ts > STALE_TIMEOUT`, the run is stale.

### Auto-Resubmit Flow

When a stale run is detected:
1. Delete `active_run:{thread_id}` key
2. Read the last user message from ThreadStore (or parse MESSAGES_SNAPSHOT from Redis events)
3. Create a new `run_id`
4. Call the segment generation pipeline internally (not via HTTP — direct function call to avoid guard conflicts)
5. Stream events from the new run through the existing SSE connection
6. The frontend sees: partial replay → stale notification → fresh generation

## Fast-Forward Replay

During XRANGE catch-up, events are emitted with delays to create a visual "fast-forward" effect:

| Event Type | Delay |
|---|---|
| STEP_STARTED / STEP_FINISHED | 200ms |
| ACTIVITY_SNAPSHOT | 150ms |
| REASONING_START/CONTENT/END | 50ms |
| TOOL_CALL_START/ARGS/END | 100ms |
| STATE_DELTA | 0ms (instant) |
| STATE_SNAPSHOT | 0ms (instant) |
| MESSAGES_SNAPSHOT | 0ms (instant) |
| RUN_STARTED / RUN_FINISHED | 0ms (instant) |
| CUSTOM | 0ms (instant) |

Total fast-forward for 8 completed nodes: ~3-4 seconds (vs 80s real-time).

## Multi-Turn Support

Each user message creates a new `run_id`. Redis stores streams per run:
```
stream:{thread_id}:{run_id_1}  → first generation
stream:{thread_id}:{run_id_2}  → follow-up refinement
```

### Run History Tracking

New Redis data structure:
```
run_history:{thread_id} → List of run_ids in order (RPUSH)
```

On reconnect:
1. If ThreadStore has full message history → emit MESSAGES_SNAPSHOT (all messages)
2. Replay only the **latest active/completed run** from Redis (not all runs)
3. ThreadStore state reflects the cumulative result of all runs

### Follow-Up Message Handling

The POST handler already supports follow-up messages (appends to ThreadStore). For reconnection:
- Previous messages are restored via MESSAGES_SNAPSHOT
- Previous segment state is restored via STATE_SNAPSHOT
- Only the latest run's events are replayed (activity, reasoning, progress)

## Multi-Tab Safety

Multiple tabs connecting to the same thread work via:

1. **POST guard (existing)**: Guard 2 checks `find_stream()` in Redis. If a stream exists (active or completed), return existing state instead of generating.
2. **Reconnect endpoint**: Each tab opens its own SSE connection to `/api/v1/reconnect/{thread_id}`. All tabs get the same events from Redis.
3. **Active generation**: Tab 1 starts generation via POST. Tab 2 opens, hits reconnect endpoint, gets catch-up + live follow. Both see the same progress.
4. **Input after completion**: Both tabs can send follow-up messages. Guard 2 prevents race conditions.

No additional backend changes needed — the existing architecture handles this naturally because:
- Redis is the single source of truth
- Each tab's SSE connection reads from the same stream
- POST guards prevent duplicate generation

## Frontend Changes

### ReconnectionBanner Enhancement

The banner shows different states:

| State | Banner Style | Text |
|---|---|---|
| Connecting | Orange, spinner | "Reconnecting to session..." |
| Catching up | Orange, progress bar | "Catching up... {node_name} ({n}/{total})" with % |
| Live follow | Green, brief | "Caught up! Following live stream..." (auto-dismiss 2s) |
| Stale recovery | Amber, warning | "Generation was interrupted — restarting automatically..." |
| Error | Red | "Could not reconnect — {error}" |

### useRestoreThread Hook Changes

New state: `reconnectPhase: "connecting" | "catching_up" | "live" | "stale_recovery" | "done" | "error"`

New event handling:
- `CUSTOM` event with `name === "run_stale"` → set phase to `stale_recovery`, reset progress
- `CUSTOM` event with `name === "run_restarted"` → set phase to `catching_up` (new run starting)
- Track catch-up completion: when first event arrives after XRANGE phase ends, transition to `live`

### useSegmentStream Hook Changes

Expose `resetProgress` callback so reconnection can clear stale progress state before auto-resubmit replay begins.

### ChatSidebar Changes

During reconnection, disable the input field and show "Reconnecting..." placeholder. Enable once reconnection completes (RUN_FINISHED or phase transitions to `done`).

## Backend Changes

### reconnect.py

1. Add stale detection logic after XRANGE
2. Add auto-resubmit flow (direct function call to pipeline)
3. Add CUSTOM event emissions for `run_stale` and `run_restarted`
4. Configurable `STALE_TIMEOUT` (default 30s) and `FAST_FORWARD_DELAY_MS` (default 200ms)

### redis_stream.py

1. Add `get_last_event_timestamp(thread_id, run_id)` — XREVRANGE with COUNT 1, return timestamp
2. Add `clear_active_run(thread_id)` — DEL active_run key
3. Add `push_run_history(thread_id, run_id)` — RPUSH to run_history list
4. Add `get_run_history(thread_id)` — LRANGE to get all run_ids

### routes.py

1. Call `push_run_history()` when starting a new run
2. No other changes needed (guards already handle multi-tab)

### middleware.py

No changes needed.

## Verification

1. **Normal flow**: Send message → 8-node pipeline → SegmentCard appears
2. **Mid-stream reload**: Start generation → reload at node 4 → banner shows "Catching up..." → fast-forwards to node 4 → transitions to "Following live..." → completes normally
3. **Post-completion reload**: Complete generation → reload → segment restores instantly from Redis replay
4. **Backend crash**: Start generation → kill backend at node 5 → restart backend → reload frontend → banner shows "interrupted — restarting" → pipeline runs again from scratch → completes
5. **Multi-tab**: Start generation in tab 1 → open same URL in tab 2 → tab 2 catches up and follows live → both see completion
6. **Follow-up message**: Complete generation → send follow-up → reload → messages restored, latest segment shown
7. **Redis down**: Stop Redis → start generation → works normally → reload → ThreadStore fallback shows state
