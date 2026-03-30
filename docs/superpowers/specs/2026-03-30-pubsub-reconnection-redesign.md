# Redis Pub/Sub Reconnection Redesign

## Problem

The current architecture uses Redis Streams for event persistence and has separate `/reconnect/{threadId}` and `/threads/{threadId}` endpoints alongside the main `/api/v1/segment` endpoint. This competes with CopilotKit's own caching and resumability mechanisms. Additionally, when an agent is started externally (by another agent) and a user opens the UI mid-execution, the current approach cannot handle this since it requires the frontend to initiate the run.

## Solution

Replace Redis Streams with Redis Pub/Sub + Redis List event buffering. Use LangGraph's MemorySaver checkpointer for graph state persistence. Consolidate to a single endpoint that handles all scenarios: new runs, reconnections, mid-execution joins, and regeneration.

## Architecture

### Three Layers

1. **Agent Service Layer** — Runs LangGraph pipeline as a background asyncio task. Publishes AG-UI events to Redis Pub/Sub channel + appends to Redis List for persistence. Uses LangGraph MemorySaver checkpointer for graph state.

2. **API Gateway Layer** — Single `POST /api/v1/segment` endpoint. Receives CopilotKit requests, infers intent from `requestType` (Chat/Connect) + Redis state + checkpointer. Streams SSE events to CopilotKit.

3. **Redis Layer** — Pub/Sub for live event fan-out. Lists for event buffering/catch-up. String keys for run tracking.

### Data Flow

```
Agent (background task)
  -> publishes to Redis Pub/Sub (agent:{thread_id}:{run_id})
  -> appends to Redis List (events:{thread_id}:{run_id})
  -> checkpoints state via LangGraph MemorySaver

Single Endpoint (POST /api/v1/segment)
  -> infers intent from CopilotKit metadata (requestType, threadId, messages)
  -> catch-up: reads Redis List + checkpointer state
  -> live: subscribes to Redis Pub/Sub
  -> streams AG-UI SSE events to CopilotKit
```

## Redis Key Structure

| Key | Type | Purpose | TTL |
|-----|------|---------|-----|
| `active_run:{thread_id}` | String | Maps thread to current active run_id | 1 hour |
| `run_status:{thread_id}:{run_id}` | String | Status: `running` / `completed` / `error` | 1 hour |
| `events:{thread_id}:{run_id}` | List | Event buffer for catch-up (RPUSH/LRANGE) | 1 hour |
| `agent:{thread_id}:{run_id}` | Pub/Sub channel | Live event streaming | N/A (ephemeral) |

## Request Intent Detection

The single endpoint determines action based on CopilotKit's `requestType` + Redis state. During implementation, the actual CopilotKit request metadata fields and event methods must be verified against the CopilotKit source/docs rather than assumed.

| Scenario | requestType | active_run? | run_status | Action |
|----------|-------------|-------------|------------|--------|
| New query | Chat | No | — | Start agent task, subscribe pub/sub, stream |
| New query (prev done) | Chat | No | completed | Start new agent task |
| Reload (same tab) | Connect | Yes | running | Replay events list, bridge to pub/sub |
| Open in new browser | Connect | Yes | running | Same as reload |
| Mid-execution join | Connect | Yes | running | Same as reload |
| Reload after completion | Connect | No | completed | Replay events from list + checkpointer state |
| Regenerate last message | Chat | Maybe | — | Detect from message count diff, clear last run, start new |
| Regenerate mid-conversation | Chat | Maybe | — | Detect from messages array diff, fork from checkpointer |

## Race Condition: List-to-Pub/Sub Transition

When switching from reading the Redis List (catch-up) to consuming Pub/Sub (live), events published during the transition could be lost. Solution: **subscribe first, read second, deduplicate**.

```
reconnect(thread_id, run_id):
  1. SUBSCRIBE agent:{thread_id}:{run_id}     <- start buffering live events
  2. LRANGE events:{thread_id}:{run_id} 0 -1  <- read all persisted events
  3. Stream all List events to client (catch-up)
  4. Note last_seq from List (= length of list)
  5. Start consuming Pub/Sub buffer:
     - Skip any event where seq <= last_seq    <- deduplicate overlap
     - Stream remaining events live
```

The agent side includes a `seq` field derived from RPUSH return value:

```python
seq = redis.rpush(f"events:{thread_id}:{run_id}", event_json)  # returns list length = seq
redis.publish(f"agent:{thread_id}:{run_id}", json.dumps({"seq": seq, "event": event_json}))
```

## Agent Service

### Run Lifecycle

```
start_agent(thread_id, run_id, query):
  1. SET active_run:{thread_id} = run_id
  2. SET run_status:{thread_id}:{run_id} = "running"
  3. Run LangGraph pipeline (with MemorySaver checkpointer)
  4. For each AG-UI event:
     a. RPUSH events:{thread_id}:{run_id} event_json
     b. PUBLISH agent:{thread_id}:{run_id} {"seq": N, "event": event_json}
  5. On completion:
     a. SET run_status:{thread_id}:{run_id} = "completed"
     b. DEL active_run:{thread_id}
     c. PUBLISH sentinel STREAM_END
  6. On error:
     a. SET run_status:{thread_id}:{run_id} = "error"
     b. DEL active_run:{thread_id}
     c. PUBLISH sentinel STREAM_ERROR
```

### LangGraph Checkpointer

- Use `MemorySaver` (in-memory) for this demo
- Checkpointer stores full graph state at each node transition
- Used for: reconstructing thread history, state snapshots on completed runs, detecting regeneration scenarios by comparing incoming messages with stored state
- Thread config: `{"configurable": {"thread_id": thread_id}}`

## Single Endpoint Flow

```
POST /api/v1/segment
  Request: threadId, messages[], metadata.requestType

  if requestType == "connect":
      run_id = GET active_run:{thread_id}
      if run_id and status == "running":
          -> subscribe-first, list-read, dedup, bridge live
      elif status == "completed":
          -> replay all events from list + checkpointer state
      else:
          -> send state from checkpointer only (no active run)

  elif requestType == "chat":
      -> compare messages with checkpointer to detect new vs regenerate
      -> start_agent() as background task
      -> subscribe to pub/sub, stream events
```

Response format: Standard AG-UI SSE (`text/event-stream`). CopilotKit consumes natively.

The endpoint never runs the agent directly — it either starts a background task or attaches to an existing one. It is always a "stream relay."

## File Changes

### Create

| File | Purpose |
|------|---------|
| `core/agent_runner.py` | Background agent task runner, pub/sub publisher, event persistence |
| `core/pubsub.py` | Redis Pub/Sub manager: subscribe, buffer, deduplicate, stream |

### Modify

| File | Change |
|------|--------|
| `agent/segment/graph.py` | Add MemorySaver checkpointer to compiled graph |
| `agent/segment/routes.py` | Rewrite to single-endpoint logic (intent detection, relay) |
| `core/middleware.py` | Remove RedisStreamMiddleware, simplify |
| `core/events.py` | Ensure events carry sequence-compatible structure |
| `main.py` | Remove reconnect/threads routers, simplify startup |
| `frontend/src/App.tsx` | Remove custom reconnection hooks, use CopilotKit natively |
| `frontend/src/hooks/` | Remove useRestoreThread.ts, simplify useAgentThread.ts |
| `frontend-next/` | Update CopilotKit config to point to single endpoint |
| `README.md` | Update architecture documentation |

### Delete

| File | Reason |
|------|--------|
| `core/redis_stream.py` | Replaced by agent_runner.py + pubsub.py |
| `api/reconnect.py` | No separate reconnect endpoint |
| `api/threads.py` | No separate threads endpoint |
| `frontend/src/hooks/useRestoreThread.ts` | CopilotKit handles SSE connection |
| `frontend/src/components/ReconnectionBanner.tsx` | No custom reconnection UI |
| `frontend/src/lib/sse.ts` | No custom SSE parsing |

## Frontend Changes

### React + Webpack (`frontend/`)

- Remove all custom reconnection logic (useRestoreThread, ReconnectionBanner, SSE parser)
- CopilotKit provider points directly to backend `/api/v1/segment`
- `useAgentThread` simplified — manages threadId in URL, CopilotKit handles connection lifecycle
- Keep: ProgressStatus, SegmentCard, ActivityIndicator, ReasoningPanel (these render from CopilotKit state)

### Next.js (`frontend-next/`)

- Update CopilotKit runtime proxy to point to single endpoint
- Same simplification — CopilotKit handles connection lifecycle

### Both Frontends

- CopilotKit's Connect flow handles reconnection on reload/new browser
- No custom SSE parsing — CopilotKit consumes AG-UI events natively
- ThreadId persisted in URL query param (existing pattern)

## Key Design Decisions

1. **Pub/Sub + List (not pure Pub/Sub):** Pub/Sub is fire-and-forget with no history. The Redis List provides catch-up capability for reconnecting clients.

2. **Subscribe-first deduplication:** Prevents event loss during the List-to-Pub/Sub transition by subscribing before reading, then deduplicating by sequence number.

3. **Backend resolves runId:** CopilotKit only knows threadId. Our backend maps thread to active run via `active_run:{thread_id}` key. This supports external agent starts.

4. **Background task (not inline):** Agent runs as asyncio background task, not inline in the request handler. This means the endpoint is always a relay, enabling multi-server scenarios where the agent runs on server A and the client connects to server B.

5. **MemorySaver checkpointer:** In-memory for this demo. Provides graph state persistence for multi-turn conversations and regeneration detection. Can be swapped for PostgresSaver or similar in production.

6. **No CopilotKit runner/caching:** CopilotKit's AgentRunner and message caching are bypassed. Our backend owns all replay/catch-up logic. This supports the use case where the agent is started externally and the user opens the UI mid-execution.
