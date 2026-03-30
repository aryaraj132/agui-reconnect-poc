# AG-UI Stream Reconnection Demo

A proof-of-concept demonstrating **SSE stream reconnection** for AI agent pipelines using the [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui), [CopilotKit](https://copilotkit.ai), Redis Pub/Sub, and LangGraph.

## Problem

In AG-UI applications, when a user reloads the browser during an active agent stream, the SSE connection drops but the backend continues processing. Events emitted after the disconnect are lost, leaving the frontend in an inconsistent state. Additionally, when an agent is started externally (by another agent or system), users opening the UI mid-execution need to catch up on events they missed.

## Solution

This demo implements two reconnection strategies side-by-side:

### Strategy 1: Redis Pub/Sub + List (`/api/v1/segment`)

Full event replay with zero event loss:

1. **Agent runs as a background task**, publishing every AG-UI event to both Redis Pub/Sub (live streaming) and a Redis List (persistence)
2. **Race-condition-safe catch-up**: subscribe to Pub/Sub first, read List second, deduplicate by sequence number
3. On reconnect, the client sees a fast-forward replay of all missed events

### Strategy 2: Checkpointer-Only (`/api/v1/stateful-segment`)

Lightweight state-snapshot catch-up without event persistence:

1. **Agent publishes to Pub/Sub only** (no Redis List)
2. **Catch-up from LangGraph MemorySaver** checkpointer state reconstructed as synthetic AG-UI events
3. On reconnect, the client jumps to the current state (no replay animation)

Both strategies share the same 8-node LangGraph pipeline and CopilotKit frontend. The difference is only in how reconnection catch-up is handled.

## Architecture

### Strategy 1: Full Event Replay (Pub/Sub + List)

```
                    New Run (Chat)
  CopilotKit ─POST─> /api/v1/segment ──> Start Background Task
    ^                     |                      |
    |                     |               LangGraph Pipeline
    |                     |                      |
    |                     v                      v
    <──── SSE ──── Pub/Sub Subscribe <── Pub/Sub Publish + List RPUSH

                    Reconnection (Connect)
  CopilotKit ─POST─> /api/v1/segment
    ^                     |
    |                1. Subscribe Pub/Sub (buffer live events)
    |                2. LRANGE Redis List (read all past events)
    |                3. Yield catch-up events (from List)
    |                4. Yield live events (from Pub/Sub, dedup by seq)
    <──── SSE ────────────┘
```

### Strategy 2: Checkpointer-Only Catch-Up

```
                    New Run (Chat)
  CopilotKit ─POST─> /api/v1/stateful-segment ──> Start Background Task
    ^                      |                             |
    |                      |                      LangGraph Pipeline
    |                      |                             |
    |                      v                             v
    <──── SSE ──── Pub/Sub Subscribe <─────── Pub/Sub Publish (only)

                    Reconnection (Connect)
  CopilotKit ─POST─> /api/v1/stateful-segment
    ^                      |
    |                 1. Subscribe Pub/Sub (buffer live events)
    |                 2. Read checkpointer state (MemorySaver)
    |                 3. Yield synthetic catch-up events (from state)
    |                 4. Yield live events (from Pub/Sub)
    <──── SSE ─────────────┘
```

### CopilotKit Integration Flow

```
  Browser                    CopilotKit Runtime              FastAPI Backend
  ──────                     ──────────────────              ──────────────
    |                              |                              |
    |── User types query ─────>   |                              |
    |                              |── POST (requestType=chat) ──>|
    |                              |                              |── Start bg task
    |                              |                              |── Publish events
    |                              |<── SSE: AG-UI events ────────|
    |<── Render progress/card ──── |                              |
    |                              |                              |
    |── Page reload ───────────>   |                              |
    |                              |── POST (requestType=connect) |
    |                              |                              |── Catch-up + live
    |                              |<── SSE: replayed events ─────|
    |<── Restore UI state ──────── |                              |
```

### Duplicate-Query Prevention

CopilotKit re-sends the full messages array after each run completes. Without protection this creates an infinite re-run loop:

```
  CopilotKit ─── POST (messages=[...]) ──> Backend
       ^                                      |
       |                                      |── Compare last human message
       |                                      |   with checkpointer state
       |                                      |
       |    (same query already processed)    |
       |<── RUN_STARTED + STATE_SNAPSHOT ─────|  <── replay segment state
       |<── RUN_FINISHED ─────────────────────|  <── CopilotKit satisfied
       |                                      |
       |    (new query)                       |
       |<── Full pipeline run ────────────────|
```

The `STATE_SNAPSHOT` in the duplicate response is critical: `RUN_STARTED` resets CopilotKit's co-agent state, so without replaying the segment data, the segment card would vanish.

## AG-UI Events Emitted Per Node

Each of the 8 pipeline nodes emits this sequence of AG-UI events:

```
STEP_STARTED
  TOOL_CALL_START  (update_progress_status)
  TOOL_CALL_ARGS   {"status":"analyzing","node":"analyze_requirements","node_index":0,"total_nodes":8}
  TOOL_CALL_END
  ACTIVITY_SNAPSHOT {"title":"Analyzing Requirements","progress":0.10,"details":"..."}
  REASONING_START
  REASONING_MESSAGE_START
  REASONING_MESSAGE_CONTENT (×3 reasoning steps)
  REASONING_MESSAGE_END
  REASONING_END
  STATE_DELTA      [{"op":"add","path":"/requirements","value":{...}}]
STEP_FINISHED
```

At pipeline start (before any node):
```
RUN_STARTED
STATE_SNAPSHOT {}                              <── clear old segment card
TOOL_CALL: update_progress_status (starting)   <── clear old progress bar
```

At pipeline end (after all nodes):
```
ACTIVITY_SNAPSHOT {"title":"Segment Complete","progress":1.0}
STATE_SNAPSHOT {name, description, condition_groups, estimated_scope}
TOOL_CALL: update_progress_status (completed)
TEXT_MESSAGE_START
TEXT_MESSAGE_CONTENT "Created segment: **...**"
TEXT_MESSAGE_END
RUN_FINISHED
```

## Pipeline Nodes

| # | Node | Progress | Purpose |
|---|------|----------|---------|
| 0 | `analyze_requirements` | 10% | Parse user query into structured requirements |
| 1 | `extract_entities` | 20% | Identify entity types (location, behavioral, demographic) |
| 2 | `validate_fields` | 30% | Validate field names against available catalog |
| 3 | `map_operators` | 45% | Map conditions to operators (equals, contains, greater_than, etc.) |
| 4 | `generate_conditions` | 55% | Build draft condition structures |
| 5 | `optimize_conditions` | 70% | Deduplicate and simplify condition groups |
| 6 | `estimate_scope` | 85% | Estimate audience size and reach |
| 7 | `build_segment` | 95% | Final segment generation with Claude (structured output) |

Each node runs for ~8-10 seconds (simulated processing), except `build_segment` which makes an actual LLM call to Claude Sonnet.

## Prerequisites

- Python 3.13+
- Node.js 18+
- Redis server (podman or docker)
- `ANTHROPIC_API_KEY` environment variable

## Quick Start

```bash
# 1. Install backend + frontend dependencies
just prepare          # React+Webpack frontend
# or
just prepare-next     # Next.js frontend

# 2. Start Redis (requires podman or docker)
just redis

# 3. Start the FastAPI backend (new terminal)
just backend

# 4. Start the frontend (new terminal)
just frontend         # React+Webpack on http://localhost:3000
# or
just frontend-next    # Next.js on http://localhost:3000
```

Open http://localhost:3000 and describe your target audience to generate a segment.

### Testing Reconnection

1. Start a segment generation (e.g., "Users from the US who signed up in the last 30 days and made a purchase")
2. While the 8-node pipeline is running (~80s), **reload the page**
3. CopilotKit automatically reconnects via the Connect flow
4. Events replay from Redis List (catch-up), then live follow via Pub/Sub
5. Pipeline completes normally with UI restored

### Testing Mid-Execution Join

1. Start generation in one browser tab
2. Copy the URL (with `?thread=...` param) to another browser/tab
3. Open it — events catch up from Redis and bridge to live

### Testing Stateful Variant

- **React frontend**: Navigate to `/stateful-segment` (any path containing "stateful")
- **Next.js frontend**: Navigate to `/stateful-segment`

Same pipeline, but reconnection uses checkpointer state snapshots instead of event replay.

## Project Structure

```
agui_stream_reconnection_demo/
├── src/stream_reconnection_demo/
│   ├── main.py                          # FastAPI app, lifespan, CORS, routers
│   ├── core/
│   │   ├── events.py                    # AG-UI EventEmitter (SSE encoding)
│   │   ├── pubsub.py                    # Redis Pub/Sub + List manager
│   │   ├── agent_runner.py              # Background asyncio task runner
│   │   └── middleware.py                # AG-UI event logging middleware
│   ├── agent/
│   │   ├── segment/
│   │   │   ├── graph.py                 # 8-node LangGraph pipeline (Claude Sonnet)
│   │   │   ├── routes.py                # POST /api/v1/segment
│   │   │   └── state.py                 # SegmentAgentState TypedDict
│   │   └── stateful_segment/
│   │       └── routes.py                # POST /api/v1/stateful-segment
│   └── schemas/
│       └── segment.py                   # Segment, Condition, ConditionGroup (Pydantic)
│
├── frontend/                            # React + Webpack (primary)
│   ├── src/
│   │   ├── App.tsx                      # CopilotKit + CopilotSidebar + main layout
│   │   ├── components/
│   │   │   ├── SegmentCard.tsx          # Final segment card (conditions, scope)
│   │   │   ├── ProgressStatus.tsx       # 8-step pipeline stepper
│   │   │   ├── ActivityIndicator.tsx    # Processing progress bar
│   │   │   ├── ReasoningPanel.tsx       # Collapsible chain-of-thought panel
│   │   │   └── Nav.tsx                  # Navigation header
│   │   ├── hooks/
│   │   │   └── useAgentThread.ts        # Thread ID + URL + browser history mgmt
│   │   └── lib/
│   │       └── types.ts                 # TypeScript interfaces
│   ├── webpack.config.js                # Webpack + embedded CopilotRuntime
│   └── package.json
│
├── frontend-next/                       # Next.js (reference)
│   ├── app/
│   │   ├── page.tsx                     # Redirects to /segment
│   │   ├── layout.tsx                   # Root layout + CopilotKit styles
│   │   ├── segment/page.tsx             # Segment builder page
│   │   ├── stateful-segment/page.tsx    # Stateful variant page
│   │   └── api/copilotkit/
│   │       ├── segment/route.ts         # CopilotRuntime proxy → /api/v1/segment
│   │       └── stateful-segment/route.ts # CopilotRuntime proxy → /api/v1/stateful-segment
│   ├── components/                      # Shared components (same as frontend/)
│   ├── hooks/useAgentThread.ts
│   ├── lib/types.ts
│   └── next.config.ts
│
├── justfile                             # Task runner commands
├── pyproject.toml                       # Python dependencies (uv)
└── uv.lock                             # Dependency lock file
```

## How It Works

### Single Endpoint, Intent Detection

Both endpoints use CopilotKit's `requestType` metadata to determine behavior:

| Scenario | requestType | Backend Action |
|----------|-------------|----------------|
| User sends new query | `chat` | Start background agent task, stream via Pub/Sub |
| CopilotKit re-sends same query | `chat` | Duplicate detected via checkpointer, return state snapshot |
| Browser reload / new tab | `connect` | Catch-up from List/checkpointer + bridge to live Pub/Sub |
| Completed run reload | `connect` | Replay segment state from checkpointer |

### Race-Condition-Safe Catch-Up (Strategy 1)

To prevent event loss during the List-to-Pub/Sub transition:

1. **Subscribe** to Pub/Sub channel first (start buffering live events)
2. **Read** all events from Redis List via `LRANGE 0 -1` (catch-up)
3. **Yield** catch-up events to client
4. **Yield** live events from Pub/Sub, skipping duplicates by sequence number

Each event gets a monotonic `seq` from `RPUSH` return value, enabling reliable deduplication.

### Checkpointer Catch-Up (Strategy 2)

1. **Subscribe** to Pub/Sub channel first (buffer live events)
2. **Read** checkpointer state via `aget_state()`
3. **Reconstruct** synthetic AG-UI events (progress status, state snapshot) from checkpointer
4. **Yield** synthetic events, then live events from Pub/Sub

### Redis Key Structure

| Key Pattern | Type | Purpose | TTL |
|-------------|------|---------|-----|
| `active_run:{thread_id}` | String | Maps thread to current active run_id | 1 hour |
| `run_status:{thread_id}:{run_id}` | String | `running` / `completed` / `error` | 1 hour |
| `events:{thread_id}:{run_id}` | List | Event buffer for catch-up (Strategy 1 only) | 1 hour |
| `agent:{thread_id}:{run_id}` | Pub/Sub | Live event streaming channel | N/A |

### CopilotKit Frontend Integration

The frontend uses CopilotKit hooks to interact with the backend:

- **`useCoAgent<Segment>({ name: "default" })`** — Reads co-agent state from `STATE_SNAPSHOT` events. Renders the segment card in the main content area (not inline in chat).
- **`useCopilotAction("update_progress_status")`** — Receives progress tool calls from the backend to update the pipeline stepper UI. Handles `status: "starting"` to clear stale progress between runs.
- **`CopilotSidebar` with `RenderMessage`** — Custom message renderer that handles `reasoning` and `activity` message roles for chain-of-thought and progress display.
- **`useAgentThread()`** — Manages thread IDs via URL query params (`?thread=...`) with browser history support. Enables mid-execution joins by sharing URLs.

### CopilotKit Runtime Configuration

**React+Webpack (`frontend/`):** CopilotRuntime is embedded directly in the webpack dev server configuration. Two proxy endpoints route to the backend:
- `/copilotkit` → `http://localhost:8000/api/v1/segment`
- `/copilotkit-stateful` → `http://localhost:8000/api/v1/stateful-segment`

**Next.js (`frontend-next/`):** CopilotRuntime is configured as API route handlers using `LangGraphHttpAgent`:
- `/api/copilotkit/segment` → `http://localhost:8000/api/v1/segment`
- `/api/copilotkit/stateful-segment` → `http://localhost:8000/api/v1/stateful-segment`

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/segment` | Segment pipeline with Pub/Sub + List catch-up |
| POST | `/api/v1/stateful-segment` | Segment pipeline with checkpointer-only catch-up |
| GET | `/health` | Health check |

### Request Body (AG-UI Protocol)

```json
{
  "threadId": "uuid",
  "runId": "uuid",
  "messages": [
    { "role": "user", "content": "Users from the US who made a purchase" }
  ],
  "metadata": {
    "requestType": "chat"
  }
}
```

### Response

SSE stream (`text/event-stream`) of AG-UI events:

```
data: {"type":"RUN_STARTED","threadId":"...","runId":"..."}

data: {"type":"STATE_SNAPSHOT","snapshot":{}}

data: {"type":"STEP_STARTED","stepName":"analyze_requirements"}

data: {"type":"TOOL_CALL_START","toolCallId":"...","toolCallName":"update_progress_status"}

...
```

## Strategy Comparison

| Feature | Strategy 1 (Pub/Sub + List) | Strategy 2 (Checkpointer-Only) |
|---------|---------------------------|-------------------------------|
| Live streaming | Redis Pub/Sub | Redis Pub/Sub |
| Event persistence | Redis List (RPUSH) | None |
| Catch-up source | Redis List (LRANGE) | LangGraph MemorySaver |
| Catch-up fidelity | Full event replay (fast-forward) | State snapshot (jump to current) |
| Missed events | Zero (List has all events) | Possible during Pub/Sub gaps |
| Redis usage | Pub/Sub + List + tracking keys | Pub/Sub + tracking keys only |
| Complexity | Higher (dedup by seq) | Lower (synthetic events) |
| Best for | Perfect replay required | State-only catch-up sufficient |

## Environment Variables

| Variable | Default | Used By |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | (required) | Backend — Claude LLM calls |
| `REDIS_URL` | `redis://localhost:6379` | Backend — Pub/Sub + persistence |
| `BACKEND_URL` | `http://localhost:8000` | React frontend — webpack proxy |
| `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:8000` | Next.js frontend — API routes |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Claude Sonnet via `langchain-anthropic` |
| Agent framework | LangGraph with MemorySaver checkpointer |
| Backend | FastAPI + Uvicorn |
| Streaming protocol | AG-UI (SSE-based) |
| Event persistence | Redis Pub/Sub + Lists |
| Frontend framework | React 19 / Next.js 15 |
| AI UI toolkit | CopilotKit (`@copilotkit/react-core`, `@copilotkit/react-ui`) |
| Styling | Tailwind CSS v4 |
| Package management | uv (Python), npm (Node.js) |
| Task runner | just |

## Development

```bash
# Lint + format check
just check

# Auto-fix lint + formatting
just fix

# Run tests
just test
```
