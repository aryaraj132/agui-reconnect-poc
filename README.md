# AG-UI Stream Reconnection Demo

A proof-of-concept demonstrating **SSE stream reconnection** for AI agent pipelines using the [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui), [CopilotKit](https://copilotkit.ai), Redis Pub/Sub, LangGraph, and the [`ag-ui-langgraph`](https://pypi.org/project/ag-ui-langgraph/) library.

## Problem

In AG-UI applications, when a user reloads the browser during an active agent stream, the SSE connection drops but the backend continues processing. Events emitted after the disconnect are lost, leaving the frontend in an inconsistent state. Additionally, when an agent is started externally (by another agent or system), users opening the UI mid-execution need to catch up on events they missed.

## Solution

This demo implements **two agents** (Segment Builder and Template Builder) with **three reconnection strategies**:

### Segment Agent — Strategy 1: Redis Pub/Sub + List (`/api/v1/segment`)

Full event replay with zero event loss:

1. **Agent runs as a background task**, publishing every AG-UI event to both Redis Pub/Sub (live streaming) and a Redis List (persistence)
2. **Race-condition-safe catch-up**: subscribe to Pub/Sub first, read List second, deduplicate by sequence number
3. On reconnect, the client sees a fast-forward replay of all missed events

### Segment Agent — Strategy 2: Checkpointer-Only (`/api/v1/stateful-segment`)

Lightweight state-snapshot catch-up without event persistence:

1. **Agent publishes to Pub/Sub only** (no Redis List)
2. **Catch-up from LangGraph MemorySaver** checkpointer state reconstructed as synthetic AG-UI events
3. On reconnect, the client jumps to the current state (no replay animation)

Both segment strategies share the same 8-node LangGraph pipeline and CopilotKit frontend. The difference is only in how reconnection catch-up is handled.

### Template Agent — `ag-ui-langgraph` + Checkpointer (`/api/v1/template`)

Uses the `ag-ui-langgraph` library for **automatic AG-UI event generation** instead of manual event emission:

1. **`LangGraphAgent.run()`** wraps `graph.astream_events()` and auto-translates LangGraph internals into AG-UI events (RUN_*, STEP_*, STATE_SNAPSHOT, TEXT_MESSAGE_*, REASONING_*)
2. **`EventAdapter`** bridges the library's event objects into SSE strings, translating custom events and filtering intermediate snapshots
3. **Checkpointer as single source of truth** — no Redis List. Catch-up on reconnect reads from checkpointer state
4. **Redis Pub/Sub** for live event delivery only (ephemeral)

## Architecture

### Segment: Strategy 1 — Full Event Replay (Pub/Sub + List)

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

### Segment: Strategy 2 — Checkpointer-Only Catch-Up

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

### Template: ag-ui-langgraph + Checkpointer

```
                    New Run (Chat)
  CopilotKit ─POST─> /api/v1/template ──> Start Background Task
    ^                     |                       |
    |                     |                LangGraphAgent.run()
    |                     |                  → EventAdapter
    |                     |                       |
    |                     v                       v
    <──── SSE ──── Pub/Sub Subscribe <── Pub/Sub Publish (only)

                    Reconnection (Connect)
  CopilotKit ─POST─> /api/v1/template
    ^                     |
    |                1. Subscribe Pub/Sub (buffer live events)
    |                2. Read checkpointer state (MemorySaver)
    |                3. Yield synthetic catch-up events (from state)
    |                4. Yield live events (from Pub/Sub)
    <──── SSE ────────────┘
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

### Duplicate-Query Prevention (Both Agents)

CopilotKit re-sends the full messages array after each run completes. Without protection this creates an infinite re-run loop:

```
  CopilotKit ─── POST (messages=[...]) ──> Backend
       ^                                      |
       |                                      |── Compare last human message
       |                                      |   with checkpointer state
       |                                      |
       |    (same query already processed)    |
       |<── RUN_STARTED + STATE_SNAPSHOT ─────|  <── replay state
       |<── RUN_FINISHED ─────────────────────|  <── CopilotKit satisfied
       |                                      |
       |    (new query)                       |
       |<── Full pipeline/agent run ──────────|
```

The `STATE_SNAPSHOT` in the duplicate response is critical: `RUN_STARTED` resets CopilotKit's co-agent state, so without replaying the state data, the segment card or template would vanish.

## AG-UI Events

### Segment Agent — Events Per Node

Each of the 8 pipeline nodes emits this sequence of manually-constructed AG-UI events:

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

### Template Agent — Events (Auto-Generated)

The `ag-ui-langgraph` library auto-generates events from `LangGraphAgent.run()`:

```
RUN_STARTED
STATE_SNAPSHOT {}                  <── injected by EventAdapter to clear old state
STEP_STARTED
  ACTIVITY_SNAPSHOT               <── translated from custom event by EventAdapter
  TEXT_MESSAGE_START              <── auto from LLM streaming
  TEXT_MESSAGE_CONTENT (×N)       <── auto from LLM streaming
  TEXT_MESSAGE_END                <── auto from LLM streaming
STEP_FINISHED
STATE_SNAPSHOT {html, css, subject, preview_text, sections, version}
RUN_FINISHED
```

Custom events dispatched from graph nodes via `adispatch_custom_event("activity_snapshot", ...)` are intercepted by the `EventAdapter` and translated to proper `ActivitySnapshotEvent` objects.

## Graph Nodes

### Segment Agent — 8-Node Pipeline

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

### Template Agent — 2-Node Graph with Conditional Routing

| Node | When | Purpose |
|------|------|---------|
| `generate_template` | No existing template | Create a new email template from user description |
| `modify_template` | Template exists | Modify existing template based on user request |

Routing is determined by `_route_by_state()`: if `state["template"] is None`, route to `generate_template`, otherwise `modify_template`. Both nodes use `ChatAnthropic.with_structured_output(EmailTemplate)` for structured LLM output.

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

Open http://localhost:3000 to see the home page with links to both agents.

### Testing Segment Agent

1. Navigate to `/segment`
2. Type a query (e.g., "Users from the US who signed up in the last 30 days and made a purchase")
3. Watch the 8-step progress stepper, reasoning panels, and activity indicators
4. Final segment card renders when pipeline completes

### Testing Template Agent

1. Navigate to `/template`
2. Type a description (e.g., "A welcome email for new SaaS users with a hero image and CTA button")
3. Watch the activity indicator during LLM generation
4. Template renders in the editor with subject, preview text, and HTML preview
5. Type a modification (e.g., "Change the CTA button to blue") — template updates with version increment

### Testing Reconnection

1. Start a segment or template generation
2. While the agent is running, **reload the page**
3. CopilotKit automatically reconnects via the Connect flow
4. For segment: events replay from Redis List (catch-up), then live follow via Pub/Sub
5. For template: catch-up from checkpointer state, then live Pub/Sub bridging

### Testing Mid-Execution Join

1. Start generation in one browser tab
2. Copy the URL (with `?thread=...` param) to another browser/tab
3. Open it — events catch up from Redis and bridge to live

### Testing Stateful Segment Variant

- **Next.js frontend**: Navigate to `/stateful-segment`

Same pipeline, but reconnection uses checkpointer state snapshots instead of event replay.

## Project Structure

```
agui_stream_reconnection_demo/
├── src/stream_reconnection_demo/
│   ├── main.py                          # FastAPI app, lifespan, CORS, routers
│   ├── core/
│   │   ├── events.py                    # AG-UI EventEmitter (SSE encoding)
│   │   ├── event_adapter.py             # Bridges LangGraphAgent → SSE strings
│   │   ├── pubsub.py                    # Redis Pub/Sub + List manager
│   │   ├── agent_runner.py              # Background asyncio task runner
│   │   └── middleware.py                # AG-UI event logging middleware
│   ├── agent/
│   │   ├── segment/
│   │   │   ├── graph.py                 # 8-node LangGraph pipeline (Claude Sonnet)
│   │   │   ├── routes.py                # POST /api/v1/segment
│   │   │   └── state.py                 # SegmentAgentState TypedDict
│   │   ├── stateful_segment/
│   │   │   └── routes.py                # POST /api/v1/stateful-segment
│   │   └── template/
│   │       ├── graph.py                 # 2-node LangGraph (generate/modify)
│   │       ├── routes.py                # POST /api/v1/template
│   │       └── state.py                 # TemplateAgentState + TemplateOutput
│   └── schemas/
│       ├── segment.py                   # Segment, Condition, ConditionGroup (Pydantic)
│       └── template.py                  # EmailTemplate, TemplateSection (Pydantic)
│
├── frontend/                            # React + Webpack (segment only)
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
├── frontend-next/                       # Next.js (both agents)
│   ├── app/
│   │   ├── page.tsx                     # Home page — card grid with agent links
│   │   ├── layout.tsx                   # Root layout + CopilotKit styles
│   │   ├── segment/page.tsx             # Segment builder page
│   │   ├── stateful-segment/page.tsx    # Stateful variant page
│   │   ├── template/page.tsx            # Template builder page
│   │   └── api/copilotkit/
│   │       ├── segment/route.ts         # CopilotRuntime proxy → /api/v1/segment
│   │       ├── stateful-segment/route.ts # CopilotRuntime proxy → /api/v1/stateful-segment
│   │       └── template/route.ts        # CopilotRuntime proxy → /api/v1/template
│   ├── components/
│   │   ├── SegmentCard.tsx              # Segment card (conditions, scope)
│   │   ├── ProgressStatus.tsx           # 8-step pipeline stepper
│   │   ├── ActivityIndicator.tsx        # Processing progress bar
│   │   ├── ReasoningPanel.tsx           # Collapsible chain-of-thought panel
│   │   ├── TemplateEditor.tsx           # Template metadata bar + preview wrapper
│   │   ├── TemplatePreview.tsx          # Sandboxed iframe HTML preview
│   │   └── Nav.tsx                      # Navigation header with active tab
│   ├── hooks/useAgentThread.ts
│   ├── lib/types.ts                     # Segment + EmailTemplate TypeScript types
│   └── next.config.ts
│
├── justfile                             # Task runner commands
├── pyproject.toml                       # Python dependencies (uv)
└── uv.lock                             # Dependency lock file
```

## How It Works

### Single Endpoint, Intent Detection

All three endpoints use CopilotKit's `requestType` metadata to determine behavior:

| Scenario | requestType | Backend Action |
|----------|-------------|----------------|
| User sends new query | `chat` | Start background agent task, stream via Pub/Sub |
| CopilotKit re-sends same query | `chat` | Duplicate detected via checkpointer, return state snapshot |
| Browser reload / new tab | `connect` | Catch-up from List/checkpointer + bridge to live Pub/Sub |
| Completed run reload | `connect` | Replay state from checkpointer |

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

**Segment Agent:**
- **`useCoAgent<Segment>({ name: "default" })`** — Reads co-agent state from `STATE_SNAPSHOT` events. Renders the segment card in the main content area.
- **`useCopilotAction("update_progress_status")`** — Receives progress tool calls from the backend to update the pipeline stepper UI.
- **`CopilotSidebar` with `RenderMessage`** — Custom message renderer for `reasoning` and `activity` message roles.
- **`useAgentThread()`** — Manages thread IDs via URL query params (`?thread=...`) with browser history support.

**Template Agent:**
- **`useCoAgent<EmailTemplate>({ name: "default" })`** — Reads template state from `STATE_SNAPSHOT` events. Renders the TemplateEditor with live HTML preview.
- **`useCoAgentStateRender`** — Inline notification in chat when template is updated.
- **`CopilotSidebar` with `RenderMessage`** — Same custom renderer pattern as segment (filters old reasoning/activity messages).
- **`useAgentThread()`** — Same thread management hook, shared across both agents.

### CopilotKit Runtime Configuration

**React+Webpack (`frontend/`):** CopilotRuntime is embedded directly in the webpack dev server configuration. Two proxy endpoints route to the backend:
- `/copilotkit` → `http://localhost:8000/api/v1/segment`
- `/copilotkit-stateful` → `http://localhost:8000/api/v1/stateful-segment`

**Next.js (`frontend-next/`):** CopilotRuntime is configured as API route handlers using `LangGraphHttpAgent`:
- `/api/copilotkit/segment` → `http://localhost:8000/api/v1/segment`
- `/api/copilotkit/stateful-segment` → `http://localhost:8000/api/v1/stateful-segment`
- `/api/copilotkit/template` → `http://localhost:8000/api/v1/template`

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/segment` | Segment pipeline with Pub/Sub + List catch-up |
| POST | `/api/v1/stateful-segment` | Segment pipeline with checkpointer-only catch-up |
| POST | `/api/v1/template` | Template agent with ag-ui-langgraph + checkpointer catch-up |
| GET | `/api/v1/template/state/{thread_id}` | Direct checkpointer read for template state |
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

| Feature | Segment: Pub/Sub + List | Segment: Checkpointer-Only | Template: ag-ui-langgraph |
|---------|------------------------|---------------------------|--------------------------|
| Live streaming | Redis Pub/Sub | Redis Pub/Sub | Redis Pub/Sub |
| Event generation | Manual (`EventEmitter`) | Manual (`EventEmitter`) | Auto (`LangGraphAgent` + `EventAdapter`) |
| Event persistence | Redis List (RPUSH) | None | None |
| Catch-up source | Redis List (LRANGE) | LangGraph MemorySaver | LangGraph MemorySaver |
| Catch-up fidelity | Full event replay | State snapshot | State snapshot |
| Redis usage | Pub/Sub + List + tracking | Pub/Sub + tracking only | Pub/Sub + tracking only |
| Complexity | Higher (dedup by seq) | Lower (synthetic events) | Lowest (library handles events) |
| Best for | Perfect replay required | State-only catch-up | Library-driven agent integration |

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
| AG-UI automation | `ag-ui-langgraph` (template agent) |
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
