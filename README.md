# AG-UI Stream Reconnection Demo

A proof-of-concept demonstrating **SSE stream reconnection** for AI agent pipelines using the [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui), Redis Streams, and LangGraph.

## Problem

In AG-UI applications, when a user reloads the browser during an active agent stream, the SSE connection drops but the backend continues processing. Events emitted after the disconnect are lost, leaving the frontend in an inconsistent state.

## Solution

This demo implements a Redis Streams-based reconnection mechanism:

1. **Every AG-UI event is persisted to Redis** before being sent to the client
2. **On browser reload**, a unified reconnect endpoint replays events from Redis (catch-up) and follows live for in-progress runs
3. **Graceful degradation** when Redis is unavailable — generation still works, reconnection falls back to in-memory state

## Architecture

```
                    Normal Flow
  Browser ──POST──> /api/v1/segment ──> LangGraph Pipeline
    ^                    |                     |
    |                    v                     v
    <──── SSE ──── EventEmitter ───> Redis Stream (XADD)
                         |
                    Middleware Stack:
                    Redis → History → Logging

                    Reconnection Flow
  Browser ──GET──> /api/v1/reconnect/{thread_id}
    ^                    |
    |                    v
    |              ThreadStore (in-memory state)
    |                    |
    |                    v
    <──── SSE ──── Redis Stream
                   Phase 1: XRANGE (catch-up, burst)
                   Phase 2: XREAD BLOCK (live follow)
```

## Prerequisites

- Python 3.13+
- Node.js 18+
- Redis server
- `ANTHROPIC_API_KEY` environment variable

## Quick Start

```bash
# 1. Install dependencies
just prepare

# 2. Start Redis (requires podman or docker)
just redis

# 3. Start the FastAPI backend (new terminal)
just backend

# 4. Start the React frontend (new terminal)
just frontend
```

Open http://localhost:3000 and describe your target audience to generate a segment.

### Testing Reconnection

1. Start a segment generation (type a query, e.g., "Users from the US who signed up in the last 30 days")
2. While the 8-node pipeline is running (~80s), **reload the page**
3. Watch the ReconnectionBanner show catch-up progress
4. Events replay from Redis, then live follow continues until generation completes

## Project Structure

```
agui_stream_reconnection_demo/
├── src/stream_reconnection_demo/
│   ├── main.py                        # FastAPI app with Redis + CORS
│   ├── core/
│   │   ├── events.py                  # AG-UI EventEmitter (SSE formatting)
│   │   ├── history.py                 # In-memory ThreadStore
│   │   ├── middleware.py              # Redis, History, Logging middlewares
│   │   └── redis_stream.py            # RedisStreamManager (XADD/XRANGE/XREAD)
│   ├── agent/segment/
│   │   ├── graph.py                   # 8-node LangGraph pipeline
│   │   ├── routes.py                  # POST /api/v1/segment (SSE streaming)
│   │   └── state.py                   # SegmentAgentState TypedDict
│   ├── schemas/
│   │   └── segment.py                 # Segment, Condition, ConditionGroup
│   └── api/
│       ├── reconnect.py               # GET /api/v1/reconnect/{thread_id}
│       └── threads.py                 # Thread CRUD endpoints
│
├── frontend/                          # React + webpack (primary)
│   ├── src/
│   │   ├── App.tsx                    # Main app component
│   │   ├── components/
│   │   │   ├── ChatSidebar.tsx        # Chat UI (replaces CopilotSidebar)
│   │   │   ├── SegmentCard.tsx        # Segment definition display
│   │   │   ├── ProgressStatus.tsx     # 8-step pipeline stepper
│   │   │   ├── ActivityIndicator.tsx  # Processing progress bar
│   │   │   ├── ReasoningPanel.tsx     # Chain-of-thought display
│   │   │   ├── ReconnectionBanner.tsx # Reconnection status banner
│   │   │   ├── AgentHistoryPanel.tsx  # Thread history sidebar
│   │   │   └── Nav.tsx                # Navigation header
│   │   ├── hooks/
│   │   │   ├── useSegmentStream.ts    # Direct SSE streaming to backend
│   │   │   ├── useRestoreThread.ts    # SSE reconnection from Redis
│   │   │   ├── useAgentThread.ts      # Thread ID + URL management
│   │   │   └── useThreadHistory.ts    # Thread list fetching
│   │   └── lib/
│   │       ├── sse.ts                 # SSE stream parser utility
│   │       └── types.ts               # TypeScript interfaces
│   ├── webpack.config.js
│   └── package.json
│
├── frontend-next/                     # Next.js + CopilotKit (reference)
├── justfile                           # Task runner
└── pyproject.toml                     # Python dependencies
```

## How Reconnection Works

### Normal Flow

```
User types query → POST /api/v1/segment → 8-node LangGraph pipeline
  Each event: Redis XADD → SSE yield to browser
  On complete: Redis STREAM_END sentinel
```

### Mid-Stream Reload

```
Browser reloads → GET /api/v1/reconnect/{thread_id}
  Phase 0: ThreadStore sends MESSAGES_SNAPSHOT + STATE_SNAPSHOT (if available)
  Phase 1: Redis XRANGE replays all persisted events (catch-up burst)
  Phase 2: Redis XREAD BLOCK follows live events until STREAM_END
  Frontend: fast-forward animation during catch-up, then live updates
```

### Post-Completion Reload

```
Browser reloads → GET /api/v1/reconnect/{thread_id}
  ThreadStore sends stored state → or Redis replays completed stream
  Frontend: instant segment restoration
```

### Redis Down

```
Generation works normally (Redis writes fail silently)
Reconnection falls back to ThreadStore (in-memory state)
If both unavailable: error returned, frontend shows fallback
```

## Pipeline Nodes

The segment agent runs an 8-node pipeline (~80-100s total):

| Node | Duration | Purpose |
|------|----------|---------|
| `analyze_requirements` | ~8s | Parse user query into structured requirements |
| `extract_entities` | ~8s | Identify entity types and fields |
| `validate_fields` | ~8s | Validate field names against schema |
| `map_operators` | ~8s | Map conditions to operators |
| `generate_conditions` | ~10s | Generate condition definitions |
| `optimize_conditions` | ~10s | Deduplicate and simplify conditions |
| `estimate_scope` | ~8s | Estimate audience size and reach |
| `build_segment` | LLM | Final segment generation with Claude |

Each node emits: `STEP_STARTED` → `TOOL_CALL` (progress) → `ACTIVITY_SNAPSHOT` → `REASONING` events → `STATE_DELTA` → `STEP_FINISHED`

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/segment` | Start segment generation (SSE stream) |
| GET | `/api/v1/reconnect/{thread_id}` | Reconnect to active/completed stream |
| GET | `/api/v1/threads` | List all threads |
| GET | `/api/v1/threads/{thread_id}` | Get thread details |
| GET | `/health` | Health check |

## AG-UI Event Types

Events follow the [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui):

| Event | Purpose |
|-------|---------|
| `RUN_STARTED` / `RUN_FINISHED` | Run lifecycle |
| `STEP_STARTED` / `STEP_FINISHED` | Pipeline node progression |
| `ACTIVITY_SNAPSHOT` | Processing status (title, progress %, details) |
| `REASONING_START/MESSAGE_CONTENT/END` | Chain-of-thought streaming |
| `STATE_SNAPSHOT` / `STATE_DELTA` | Agent state updates |
| `TEXT_MESSAGE_START/CONTENT/END` | Assistant text streaming |
| `TOOL_CALL_START/ARGS/END` | Tool invocations (progress updates) |
| `MESSAGES_SNAPSHOT` | Message history restoration |

## Frontend Variants

- **`frontend/`** (primary) — React + webpack, direct SSE to backend. No proxy layer, clean reconnection via Redis.
- **`frontend-next/`** (reference) — Next.js + CopilotKit. Uses CopilotRuntime as proxy between browser and backend. Kept for comparison.

## Environment Variables

| Variable | Default | Used By |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | (required) | Backend — LLM calls |
| `REDIS_URL` | `redis://localhost:6379` | Backend — stream persistence |
| `BACKEND_URL` | `http://localhost:8000` | Frontend — API base URL |
