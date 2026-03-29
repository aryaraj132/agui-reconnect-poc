# Reconnection Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stale-run detection with auto-resubmit, fast-forward replay delays, multi-turn run history, and enhanced reconnection UX to the existing stream reconnection demo.

**Architecture:** The unified reconnect endpoint (`GET /api/v1/reconnect/{thread_id}`) gains three new paths: STALE (detects dead runs, replays partial events, auto-resubmits), FAST-FORWARD (configurable per-event-type delays during XRANGE catch-up), and MULTI-TURN (tracks run history per thread, replays only the latest run). The frontend gets phase-aware reconnection states and an enhanced banner.

**Tech Stack:** Python 3.13/FastAPI, Redis Streams, LangGraph, React 19/webpack, TypeScript, Tailwind CSS v4

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/stream_reconnection_demo/core/redis_stream.py` | Add `get_last_event_timestamp()`, `clear_active_run()`, `push_run_history()`, `get_run_history()` |
| Modify | `src/stream_reconnection_demo/api/reconnect.py` | Add stale detection, auto-resubmit, fast-forward delays, CUSTOM events |
| Modify | `src/stream_reconnection_demo/agent/segment/routes.py` | Call `push_run_history()` on run start; extract pipeline runner for reuse |
| Modify | `frontend/src/hooks/useRestoreThread.ts` | Add `reconnectPhase` state, handle CUSTOM events, configurable fast-forward delays |
| Modify | `frontend/src/hooks/useSegmentStream.ts` | Expose `resetProgress` callback |
| Modify | `frontend/src/components/ReconnectionBanner.tsx` | Phase-specific banner styles (connecting, catching_up, live, stale_recovery, error) |
| Modify | `frontend/src/components/ChatSidebar.tsx` | Disable input during reconnection |
| Modify | `frontend/src/App.tsx` | Pass reconnection phase to ChatSidebar and banner |

---

### Task 1: Add Redis Helper Methods

**Files:**
- Modify: `src/stream_reconnection_demo/core/redis_stream.py:176-198` (after `get_active_run`, before `read_events`)

- [ ] **Step 1: Add `get_last_event_timestamp` method**

Add after `get_active_run` (line 178), before `find_stream` (line 180):

```python
async def get_last_event_timestamp(self, thread_id: str, run_id: str) -> float | None:
    """Return the Unix timestamp of the most recent event in the stream.

    Uses XREVRANGE with COUNT 1 to efficiently get the last entry.
    Returns None if the stream is empty or doesn't exist.
    """
    key = self._stream_key(thread_id, run_id)
    entries = await self._redis.xrevrange(key, count=1)
    if not entries:
        return None
    _msg_id, fields = entries[0]
    ts_str = fields.get("ts", "")
    if ts_str:
        try:
            return float(ts_str)
        except (ValueError, TypeError):
            pass
    # Fallback: parse the Redis message ID (millisecond timestamp)
    msg_id_str = entries[0][0]
    try:
        return int(msg_id_str.split("-")[0]) / 1000.0
    except (ValueError, IndexError):
        return None
```

- [ ] **Step 2: Add `clear_active_run` method**

Add immediately after `get_last_event_timestamp`:

```python
async def clear_active_run(self, thread_id: str) -> None:
    """Delete the active_run key for a thread.

    Used during stale run cleanup to allow new runs to start.
    """
    await self._redis.delete(self._active_key(thread_id))
    logger.info("Cleared active_run for thread %s", thread_id)
```

- [ ] **Step 3: Add `push_run_history` and `get_run_history` methods**

Add immediately after `clear_active_run`:

```python
async def push_run_history(self, thread_id: str, run_id: str) -> None:
    """Append a run_id to the thread's run history list."""
    key = f"run_history:{thread_id}"
    await self._redis.rpush(key, run_id)
    await self._redis.expire(key, STREAM_TTL)
    logger.info("Pushed run %s to history for thread %s", run_id, thread_id)

async def get_run_history(self, thread_id: str) -> list[str]:
    """Return all run_ids for a thread in chronological order."""
    key = f"run_history:{thread_id}"
    return await self._redis.lrange(key, 0, -1)
```

- [ ] **Step 4: Verify no syntax errors**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.core.redis_stream import RedisStreamManager; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/stream_reconnection_demo/core/redis_stream.py
git commit -m "feat: add redis helpers for stale detection and run history"
```

---

### Task 2: Register Run History in Routes

**Files:**
- Modify: `src/stream_reconnection_demo/agent/segment/routes.py:213-217`

- [ ] **Step 1: Add `push_run_history` call after `start_run`**

In `generate_segment`, after the existing `start_run` call (line 215), add `push_run_history`:

```python
    # Register this run in Redis
    try:
        await redis_manager.start_run(thread_id, run_id)
    except Exception:
        logging.warning("Redis start_run failed, streaming without persistence")

    try:
        await redis_manager.push_run_history(thread_id, run_id)
    except Exception:
        logging.warning("Redis push_run_history failed")
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.agent.segment.routes import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/segment/routes.py
git commit -m "feat: register run_id in run history on generation start"
```

---

### Task 3: Extract Pipeline Runner for Reuse

The auto-resubmit flow in the reconnect endpoint needs to run the segment pipeline. Rather than importing the full route handler, extract the core event-emitting generator into a reusable function.

**Files:**
- Modify: `src/stream_reconnection_demo/agent/segment/routes.py`

- [ ] **Step 1: Extract `run_segment_pipeline` generator function**

Add a new top-level async generator function above `generate_segment` (before line 124). This function takes the graph, query, thread_id, run_id, prior_messages and yields SSE events — it contains the logic currently inside `event_stream()` (lines 219-395).

```python
async def run_segment_pipeline(
    segment_graph,
    query: str,
    thread_id: str,
    run_id: str,
    prior_messages: list[dict] | None = None,
) -> AsyncIterator[str]:
    """Run the 8-node segment pipeline, yielding AG-UI SSE events.

    This is the core generation logic, extracted so it can be called
    from both the POST handler and the reconnect auto-resubmit flow.
    """
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
                    activity_id,
                    "processing",
                    {
                        "title": meta["title"],
                        "progress": meta["progress"],
                        "details": meta["details"],
                    },
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

                if node_name == "build_segment":
                    result_segment = node_output.get("segment")

                yield emitter.emit_step_finish(node_name)

        if result_segment is None:
            yield emitter.emit_run_error("Segment generation produced no result")
            return

        segment_dict = result_segment.model_dump()
        thread_store.update_state(thread_id, segment_dict)

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
```

- [ ] **Step 2: Update `generate_segment` to call `run_segment_pipeline`**

Replace the `event_stream()` nested function and its contents (lines 219-395) with a delegation to the extracted function:

```python
    async def event_stream():
        async for event in run_segment_pipeline(
            segment_graph, query, thread_id, run_id, prior_messages
        ):
            yield event

    raw_stream = event_stream()
```

The middleware pipeline wrapping (`LoggingMiddleware`, `HistoryMiddleware`, `RedisStreamMiddleware`) stays unchanged.

- [ ] **Step 3: Add missing import**

Add at top of file (after existing imports):

```python
from typing import AsyncIterator
```

- [ ] **Step 4: Verify no syntax errors**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.agent.segment.routes import router, run_segment_pipeline; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/stream_reconnection_demo/agent/segment/routes.py
git commit -m "refactor: extract run_segment_pipeline for reuse by reconnect"
```

---

### Task 4: Add Stale Detection and Fast-Forward to Reconnect Endpoint

**Files:**
- Modify: `src/stream_reconnection_demo/api/reconnect.py`

- [ ] **Step 1: Add imports and constants**

Add at the top of `reconnect.py`, after existing imports:

```python
import asyncio
import time

from stream_reconnection_demo.agent.segment.routes import run_segment_pipeline, NODE_META, TOTAL_NODES
```

Add after the `CATCHUP_SKIP_TYPES` constant (line 36):

```python
# Stale run timeout in seconds
STALE_TIMEOUT = 30

# Fast-forward delays per event type (in seconds) during XRANGE catch-up
FAST_FORWARD_DELAYS: dict[str, float] = {
    "STEP_STARTED": 0.2,
    "STEP_FINISHED": 0.2,
    "ACTIVITY_SNAPSHOT": 0.15,
    "REASONING_START": 0.05,
    "REASONING_MESSAGE_START": 0.0,
    "REASONING_MESSAGE_CONTENT": 0.05,
    "REASONING_MESSAGE_END": 0.0,
    "REASONING_END": 0.05,
    "TOOL_CALL_START": 0.1,
    "TOOL_CALL_ARGS": 0.1,
    "TOOL_CALL_END": 0.1,
    "STATE_DELTA": 0.0,
    "STATE_SNAPSHOT": 0.0,
    "MESSAGES_SNAPSHOT": 0.0,
    "RUN_STARTED": 0.0,
    "RUN_FINISHED": 0.0,
    "CUSTOM": 0.0,
}
```

- [ ] **Step 2: Add stale detection after XRANGE catch-up**

In the `replay_stream()` function, after the catch-up loop processes entries (after the `for msg_id, fields in entries:` loop, around line 161), add stale detection before the `if stream_ended:` check:

```python
        # --- Stale detection ---
        if not stream_ended and is_active and entries:
            try:
                last_ts = await redis_manager.get_last_event_timestamp(
                    thread_id, run_id
                )
                if last_ts is not None:
                    age = time.time() - last_ts
                    if age > STALE_TIMEOUT:
                        logger.warning(
                            "Reconnect: STALE run %s for %s (last event %.0fs ago)",
                            run_id, thread_id, age,
                        )
                        is_active = False
                        stream_ended = True  # Don't enter live follow

                        # Notify frontend
                        yield emitter.emit_custom(
                            "run_stale",
                            {"reason": "no_heartbeat", "age_seconds": age},
                        )

                        # Clear stale active_run key
                        await redis_manager.clear_active_run(thread_id)

                        # Auto-resubmit: find last user query
                        last_query = None
                        thread = thread_store.get_thread(thread_id)
                        if thread and thread["messages"]:
                            for msg in reversed(thread["messages"]):
                                if msg.get("role") == "user":
                                    last_query = msg.get("content", "")
                                    break

                        if last_query:
                            # Notify frontend that we're restarting
                            yield emitter.emit_custom(
                                "run_restarted",
                                {"reason": "auto_resubmit"},
                            )

                            # Start new run
                            new_run_id = str(uuid.uuid4())
                            segment_graph = request.app.state.segment_graph

                            try:
                                await redis_manager.start_run(thread_id, new_run_id)
                                await redis_manager.push_run_history(thread_id, new_run_id)
                            except Exception:
                                logger.warning("Redis start for resubmit failed")

                            # Run pipeline and forward events through this SSE connection
                            from stream_reconnection_demo.core.middleware import RedisStreamMiddleware

                            raw_pipeline = run_segment_pipeline(
                                segment_graph,
                                last_query,
                                thread_id,
                                new_run_id,
                            )

                            # Wrap with Redis middleware so new events are persisted
                            persisted_pipeline = RedisStreamMiddleware(
                                redis_manager, thread_id, new_run_id
                            ).apply(raw_pipeline)

                            async for event in persisted_pipeline:
                                yield event
                            return
                        else:
                            logger.warning(
                                "Reconnect: stale run but no user query to resubmit for %s",
                                thread_id,
                            )
            except Exception:
                logger.warning("Stale detection failed for %s", thread_id)
```

- [ ] **Step 3: Add fast-forward delays to catch-up loop**

In the catch-up loop, after yielding the replayed event data (`yield event_data` around line 160), add a delay:

```python
            # Replay this event
            event_data = fields.get("data", "")
            if event_data:
                yield event_data
                # Fast-forward delay based on event type
                delay = FAST_FORWARD_DELAYS.get(event_type, 0.0)
                if delay > 0:
                    await asyncio.sleep(delay)
```

- [ ] **Step 4: Emit CUSTOM event for catch-up phase transition**

After the catch-up loop ends and before the live follow phase begins (before the existing `# --- Phase 3: Live follow` comment), add a catch-up-complete signal:

```python
        # Signal catch-up complete before entering live follow
        yield emitter.emit_custom(
            "catchup_complete",
            {"replayed_count": len(entries)},
        )
```

- [ ] **Step 5: Verify no syntax errors**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.api.reconnect import router; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/stream_reconnection_demo/api/reconnect.py
git commit -m "feat: add stale detection, auto-resubmit, and fast-forward delays to reconnect"
```

---

### Task 5: Add `reconnectPhase` to `useRestoreThread`

**Files:**
- Modify: `frontend/src/hooks/useRestoreThread.ts`

- [ ] **Step 1: Add `reconnectPhase` type and state**

At the top of the file, add the phase type:

```typescript
export type ReconnectPhase =
  | "idle"
  | "connecting"
  | "catching_up"
  | "live"
  | "stale_recovery"
  | "done"
  | "error";
```

In the hook function, add the state variable alongside the existing ones (after `isCatchingUp` state):

```typescript
const [reconnectPhase, setReconnectPhase] = useState<ReconnectPhase>("idle");
```

- [ ] **Step 2: Wire phase transitions to existing logic**

Update the existing state transitions in the hook:

1. When the SSE connection is initiated (around line 106): set phase to `"connecting"`
2. When the first event arrives from catch-up: set phase to `"catching_up"`
3. When `CUSTOM` event with `name === "catchup_complete"` arrives: set phase to `"live"`
4. When `CUSTOM` event with `name === "run_stale"` arrives: set phase to `"stale_recovery"`, reset activity/reasoning
5. When `CUSTOM` event with `name === "run_restarted"` arrives: set phase to `"catching_up"` (new run starting)
6. On `RUN_FINISHED`: set phase to `"done"`
7. On `RUN_ERROR` or catch failure: set phase to `"error"`

In the event handling loop, add a `CUSTOM` event handler (add after the `REASONING_MESSAGE_CONTENT` handler, before `RUN_FINISHED`):

```typescript
          } else if (type === "CUSTOM") {
            const customName = event.name as string;
            if (customName === "run_stale") {
              setReconnectPhase("stale_recovery");
              setCurrentActivity(null);
              setCurrentReasoning("");
            } else if (customName === "run_restarted") {
              setReconnectPhase("catching_up");
            } else if (customName === "catchup_complete") {
              setReconnectPhase("live");
              setIsCatchingUp(false);
            }
```

- [ ] **Step 3: Update hook return value**

Add `reconnectPhase` to the returned object:

```typescript
  return {
    isRestoring,
    isStreamActive,
    isCatchingUp,
    reconnectPhase,
    currentActivity: threadData ? currentActivity : null,
    currentReasoning: threadData ? currentReasoning : "",
    restoredSegment,
  };
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx tsc --noEmit`
Expected: No errors (or only pre-existing errors unrelated to this change)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useRestoreThread.ts
git commit -m "feat: add reconnectPhase state to useRestoreThread"
```

---

### Task 6: Add `resetProgress` to `useSegmentStream`

**Files:**
- Modify: `frontend/src/hooks/useSegmentStream.ts`

- [ ] **Step 1: Add `resetProgress` callback**

After the `sendMessage` callback definition (around line 278), add:

```typescript
  const resetProgress = useCallback(() => {
    setProgressStatus(null);
    setCurrentActivity(null);
    setCurrentReasoning("");
  }, []);
```

- [ ] **Step 2: Add to return object**

Add `resetProgress` to the returned object:

```typescript
  return {
    messages,
    segment,
    progressStatus,
    currentActivity,
    currentReasoning,
    isGenerating,
    sendMessage,
    setMessages,
    setSegment,
    resetProgress,
  };
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useSegmentStream.ts
git commit -m "feat: expose resetProgress callback from useSegmentStream"
```

---

### Task 7: Enhance ReconnectionBanner with Phase-Specific Styles

**Files:**
- Modify: `frontend/src/components/ReconnectionBanner.tsx`

- [ ] **Step 1: Update props interface**

Replace the current props with phase-aware props:

```typescript
import type { ReconnectPhase } from "@/hooks/useRestoreThread";
import type { ActivityContent } from "@/hooks/useSegmentStream";

interface ReconnectionBannerProps {
  reconnectPhase: ReconnectPhase;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
}
```

- [ ] **Step 2: Rewrite the component with phase-specific rendering**

Replace the component body:

```typescript
export function ReconnectionBanner({
  reconnectPhase,
  currentActivity,
  currentReasoning,
}: ReconnectionBannerProps) {
  if (reconnectPhase === "idle" || reconnectPhase === "done") return null;

  const progress = currentActivity?.progress
    ? Math.round(currentActivity.progress * 100)
    : null;

  // Phase-specific config
  const phaseConfig: Record<
    string,
    { bg: string; icon: string; text: string }
  > = {
    connecting: {
      bg: "from-orange-600 to-amber-600",
      icon: "animate-spin",
      text: "Reconnecting to session...",
    },
    catching_up: {
      bg: "from-orange-600 to-amber-600",
      icon: "animate-spin",
      text: currentActivity?.title
        ? `Catching up... ${currentActivity.title}${progress !== null ? ` (${progress}%)` : ""}`
        : "Catching up...",
    },
    live: {
      bg: "from-green-600 to-emerald-600",
      icon: "",
      text: "Caught up! Following live stream...",
    },
    stale_recovery: {
      bg: "from-amber-600 to-yellow-600",
      icon: "animate-pulse",
      text: "Generation was interrupted — restarting automatically...",
    },
    error: {
      bg: "from-red-600 to-rose-600",
      icon: "",
      text: "Could not reconnect",
    },
  };

  const config = phaseConfig[reconnectPhase] || phaseConfig.connecting;

  return (
    <div
      className={`fixed top-0 left-0 right-0 z-50 bg-gradient-to-r ${config.bg} text-white px-4 py-2 shadow-lg`}
    >
      <div className="max-w-4xl mx-auto flex items-center gap-3">
        {/* Spinner/icon */}
        {config.icon && (
          <div
            className={`w-4 h-4 border-2 border-white/30 border-t-white rounded-full ${config.icon}`}
          />
        )}

        {/* Status text */}
        <span className="text-sm font-medium flex-1">{config.text}</span>

        {/* Progress bar (catching_up and stale_recovery only) */}
        {(reconnectPhase === "catching_up" ||
          reconnectPhase === "stale_recovery") &&
          progress !== null && (
            <div className="w-32 h-1.5 bg-white/20 rounded-full overflow-hidden">
              <div
                className="h-full bg-white rounded-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}
      </div>

      {/* Details row */}
      {reconnectPhase === "catching_up" && currentActivity?.details && (
        <div className="max-w-4xl mx-auto mt-1">
          <span className="text-xs text-white/70 truncate block">
            {currentActivity.details}
          </span>
        </div>
      )}

      {/* Reasoning (catching_up only) */}
      {reconnectPhase === "catching_up" && currentReasoning && (
        <div className="max-w-4xl mx-auto mt-1">
          <span className="text-xs text-white/60 font-mono truncate block">
            {currentReasoning.slice(-80)}
          </span>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Auto-dismiss for "live" phase**

The `live` phase should auto-dismiss after 2 seconds. Add the auto-dismiss logic with a local state:

```typescript
import { useState, useEffect } from "react";
```

Add inside the component, before the early return:

```typescript
  const [liveDismissed, setLiveDismissed] = useState(false);

  useEffect(() => {
    if (reconnectPhase === "live") {
      const timer = setTimeout(() => setLiveDismissed(true), 2000);
      return () => clearTimeout(timer);
    }
    setLiveDismissed(false);
  }, [reconnectPhase]);

  if (
    reconnectPhase === "idle" ||
    reconnectPhase === "done" ||
    (reconnectPhase === "live" && liveDismissed)
  )
    return null;
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ReconnectionBanner.tsx
git commit -m "feat: phase-specific reconnection banner styles"
```

---

### Task 8: Disable ChatSidebar Input During Reconnection

**Files:**
- Modify: `frontend/src/components/ChatSidebar.tsx`

- [ ] **Step 1: Add `isReconnecting` prop**

Add to the `ChatSidebarProps` interface:

```typescript
interface ChatSidebarProps {
  messages: Message[];
  isGenerating: boolean;
  isReconnecting: boolean;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
  onSendMessage: (content: string) => void;
  children: React.ReactNode;
}
```

Destructure it in the function parameters:

```typescript
export function ChatSidebar({
  messages,
  isGenerating,
  isReconnecting,
  currentActivity,
  currentReasoning,
  onSendMessage,
  children,
}: ChatSidebarProps) {
```

- [ ] **Step 2: Update input disabled state and placeholder**

Change the `disabled` condition on the input and button from `isGenerating` to `isGenerating || isReconnecting`:

```typescript
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                isReconnecting
                  ? "Reconnecting..."
                  : isGenerating
                    ? "Generating segment..."
                    : "Describe your target audience..."
              }
              disabled={isGenerating || isReconnecting}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-500 focus:outline-none focus:border-purple-500 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isGenerating || isReconnecting || !input.trim()}
              className="bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Send
            </button>
```

Also update the `handleSubmit` guard:

```typescript
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isGenerating || isReconnecting) return;
    onSendMessage(trimmed);
    setInput("");
  };
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx tsc --noEmit`
Expected: Errors about `App.tsx` not passing `isReconnecting` prop (will be fixed in Task 9)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ChatSidebar.tsx
git commit -m "feat: disable chat input during reconnection"
```

---

### Task 9: Wire Everything Together in App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update destructured values from hooks**

Update the `useRestoreThread` destructuring to include `reconnectPhase`:

```typescript
  const {
    isRestoring,
    isStreamActive,
    isCatchingUp,
    reconnectPhase,
    currentActivity: restoreActivity,
    currentReasoning: restoreReasoning,
    restoredSegment,
  } = useRestoreThread(threadId, isExistingThread, setMessages, setSegment);
```

- [ ] **Step 2: Compute `isReconnecting` flag**

Add after the existing `activeReasoning` merge logic:

```typescript
  const isReconnecting =
    reconnectPhase !== "idle" && reconnectPhase !== "done";
```

- [ ] **Step 3: Update ReconnectionBanner props**

Replace the existing `ReconnectionBanner` props with the new phase-based API:

```typescript
          <ReconnectionBanner
            reconnectPhase={reconnectPhase}
            currentActivity={restoreActivity}
            currentReasoning={restoreReasoning}
          />
```

- [ ] **Step 4: Pass `isReconnecting` to ChatSidebar**

Add the prop:

```typescript
      <ChatSidebar
        messages={messages}
        isGenerating={isGenerating}
        isReconnecting={isReconnecting}
        currentActivity={activeActivity}
        currentReasoning={activeReasoning}
        onSendMessage={sendMessage}
      >
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: wire reconnectPhase through App to banner and chat input"
```

---

### Task 10: End-to-End Verification

- [ ] **Step 1: Start Redis**

Run: `just redis`

- [ ] **Step 2: Start backend**

Run: `just backend`

- [ ] **Step 3: Start frontend**

Run: `just frontend`

- [ ] **Step 4: Test normal flow**

Open http://localhost:3000. Type "Users from the US who signed up in the last 30 days". Verify 8-node pipeline runs, SegmentCard appears.

- [ ] **Step 5: Test mid-stream reload**

Start a new generation. At ~node 4, reload the page. Verify:
- Banner shows "Reconnecting to session..." (orange, connecting phase)
- Banner transitions to "Catching up..." with progress (orange, catching_up phase)
- Events replay with ~200ms delays (visible fast-forward)
- Banner transitions to "Caught up! Following live stream..." (green, live phase)
- Green banner auto-dismisses after 2 seconds
- Generation completes normally

- [ ] **Step 6: Test post-completion reload**

After generation completes, reload. Verify segment restores from Redis replay with fast-forward animation.

- [ ] **Step 7: Test backend crash (stale recovery)**

Start generation. Kill the backend (Ctrl+C) at ~node 5. Wait 35 seconds. Restart backend. Reload frontend. Verify:
- Partial events replay (fast-forward)
- Banner shows "Generation was interrupted — restarting automatically..." (amber, stale_recovery)
- Pipeline restarts from scratch
- Generation completes normally

- [ ] **Step 8: Test multi-tab**

Start generation in tab 1. Open same URL in tab 2. Verify tab 2 catches up and follows live. Both tabs see completion.

- [ ] **Step 9: Commit final state**

```bash
git add -A
git commit -m "feat: reconnection improvements — stale detection, fast-forward, phase UX"
```
