# AG-UI Stream Reconnection Demo -- Comprehensive Walkthrough

## Table of Contents

- [1. Project Overview](#1-project-overview)
- [2. Architecture & Data Flow](#2-architecture--data-flow)
  - [2.1 System Architecture](#21-system-architecture)
  - [2.2 Strategy 1: Full Event Replay (Pub/Sub + List)](#22-strategy-1-full-event-replay-pubsub--list)
  - [2.3 Strategy 2: Checkpointer-Only Catch-Up](#23-strategy-2-checkpointer-only-catch-up)
  - [2.4 CopilotKit Integration Flow](#24-copilotkit-integration-flow)
  - [2.5 Duplicate-Query Prevention](#25-duplicate-query-prevention)
- [3. Root Configuration Files](#3-root-configuration-files)
  - [3.1 pyproject.toml](#31-pyprojecttoml)
  - [3.2 justfile](#32-justfile)
  - [3.3 .gitignore](#33-gitignore)
- [4. Backend (Python)](#4-backend-python)
  - [4.1 Entry Point: main.py](#41-entry-point-mainpy)
  - [4.2 Schemas](#42-schemas)
    - [4.2.1 schemas/segment.py](#421-schemassegmentpy)
  - [4.3 Core Infrastructure](#43-core-infrastructure)
    - [4.3.1 core/events.py](#431-coreeventspy)
    - [4.3.2 core/pubsub.py](#432-corepubsubpy)
    - [4.3.3 core/agent_runner.py](#433-coreagent_runnerpy)
    - [4.3.4 core/middleware.py](#434-coremiddlewarepy)
  - [4.4 Agent: Segment Pipeline](#44-agent-segment-pipeline)
    - [4.4.1 agent/segment/state.py](#441-agentsegmentstatepy)
    - [4.4.2 agent/segment/graph.py](#442-agentsegmentgraphpy)
    - [4.4.3 agent/segment/routes.py](#443-agentsegmentroutespy)
  - [4.5 Agent: Stateful Segment Pipeline](#45-agent-stateful-segment-pipeline)
    - [4.5.1 agent/stateful_segment/routes.py](#451-agentstateful_segmentroutespy)
- [5. Frontend: React + Webpack](#5-frontend-react--webpack)
  - [5.1 Configuration](#51-configuration)
    - [5.1.1 package.json](#511-packagejson)
    - [5.1.2 webpack.config.js](#512-webpackconfigjs)
  - [5.2 Entry Point & App Shell](#52-entry-point--app-shell)
    - [5.2.1 src/index.tsx](#521-srcindextsx)
    - [5.2.2 src/App.tsx](#522-srcapptsx)
  - [5.3 Hooks](#53-hooks)
    - [5.3.1 hooks/useAgentThread.ts](#531-hooksuseagentthreadts)
  - [5.4 Components](#54-components)
    - [5.4.1 components/Nav.tsx](#541-componentsnavtsx)
    - [5.4.2 components/SegmentCard.tsx](#542-componentssegmentcardtsx)
    - [5.4.3 components/ProgressStatus.tsx](#543-componentsprogressstatustsx)
    - [5.4.4 components/ActivityIndicator.tsx](#544-componentsactivityindicatortsx)
    - [5.4.5 components/ReasoningPanel.tsx](#545-componentsreasoningpaneltsx)
  - [5.5 Types & Styles](#55-types--styles)
    - [5.5.1 lib/types.ts](#551-libtypests)
    - [5.5.2 src/globals.css](#552-srcglobalscss)
- [6. Frontend: Next.js](#6-frontend-nextjs)
  - [6.1 Configuration](#61-configuration)
    - [6.1.1 package.json](#611-packagejson)
    - [6.1.2 next.config.ts](#612-nextconfigts)
  - [6.2 App Router Pages](#62-app-router-pages)
    - [6.2.1 app/layout.tsx](#621-applayouttsx)
    - [6.2.2 app/page.tsx](#622-apppagetsx)
    - [6.2.3 app/segment/page.tsx](#623-appsegmentpagetsx)
    - [6.2.4 app/stateful-segment/page.tsx](#624-appstateful-segmentpagetsx)
  - [6.3 API Routes (CopilotRuntime Proxy)](#63-api-routes-copilotruntime-proxy)
    - [6.3.1 api/copilotkit/segment/route.ts](#631-apicopilotkitsegmentroutets)
    - [6.3.2 api/copilotkit/stateful-segment/route.ts](#632-apicopilotkitstateful-segmentroutets)
  - [6.4 Shared Components, Hooks, Types](#64-shared-components-hooks-types)
- [7. End-to-End Request Lifecycle](#7-end-to-end-request-lifecycle)
  - [7.1 New Query (Chat Flow)](#71-new-query-chat-flow)
  - [7.2 Reconnection (Connect Flow)](#72-reconnection-connect-flow)
  - [7.3 Duplicate Query Prevention](#73-duplicate-query-prevention)

---

## 1. Project Overview

This project is a proof-of-concept demonstrating **SSE stream reconnection** for AI agent pipelines. The core problem: in AG-UI applications, when a user reloads the browser during an active agent stream, the SSE connection drops but the backend continues processing. Events emitted after disconnect are lost, leaving the frontend in an inconsistent state.

The demo implements two reconnection strategies side-by-side using the same 8-node LangGraph pipeline:

| Strategy | Endpoint | Catch-Up Source | Fidelity |
|----------|----------|-----------------|----------|
| **Pub/Sub + List** | `POST /api/v1/segment` | Redis List (LRANGE) | Full event replay |
| **Checkpointer-Only** | `POST /api/v1/stateful-segment` | LangGraph MemorySaver | State snapshot jump |

**Tech stack:**

| Layer | Technology |
|-------|-----------|
| LLM | Claude Sonnet via `langchain-anthropic` |
| Agent framework | LangGraph with MemorySaver checkpointer |
| Backend | FastAPI + Uvicorn |
| Streaming protocol | AG-UI (SSE-based) |
| Event persistence | Redis Pub/Sub + Lists |
| Frontend (primary) | React 19 + Webpack |
| Frontend (reference) | Next.js 15 |
| AI UI toolkit | CopilotKit |
| Styling | Tailwind CSS v4 |
| Package management | uv (Python), npm (Node.js) |

**Prerequisites:** Python 3.13+, Node.js 18+, Redis (via podman/docker), `ANTHROPIC_API_KEY` environment variable.

---

## 2. Architecture & Data Flow

### 2.1 System Architecture

The system has three layers:

```
Browser (React/Next.js)
    |
    |  CopilotKit JSON-RPC  →  CopilotRuntime (proxy)  →  HTTP POST
    |                                                       |
    v                                                       v
CopilotKit Sidebar                                    FastAPI Backend
(sends messages,                                      (port 8000)
 receives SSE events)                                      |
    ^                                                      |
    |                                                      v
    |                                              LangGraph Pipeline
    |                                              (8 nodes, ~80s total)
    |                                                      |
    |                                                      v
    |                                              Redis (port 6379)
    |                                              ├── Pub/Sub channels
    |                                              ├── Lists (event log)
    |                                              └── String keys (status)
    |                                                      |
    +<── SSE event stream (text/event-stream) ─────────────+
```

The CopilotKit runtime acts as a middleware proxy between the browser and the FastAPI backend. In the React+Webpack frontend, it runs embedded in the webpack dev server. In Next.js, it runs as API route handlers.

### 2.2 Strategy 1: Full Event Replay (Pub/Sub + List)

Every AG-UI event is persisted in a Redis List via `RPUSH` and simultaneously published to a Pub/Sub channel. The `RPUSH` return value serves as a monotonic sequence number for deduplication.

**New Run (Chat):**

```
CopilotKit ─POST─> /api/v1/segment ──> Start Background Task
  ^                     |                      |
  |                     |               LangGraph Pipeline
  |                     |                      |
  |                     v                      v
  <──── SSE ──── Pub/Sub Subscribe <── Pub/Sub Publish + List RPUSH
```

**Reconnection (Connect):**

```
CopilotKit ─POST─> /api/v1/segment
  ^                     |
  |                1. Subscribe Pub/Sub (buffer live events)
  |                2. LRANGE Redis List (read all past events)
  |                3. Yield catch-up events (from List)
  |                4. Yield live events (from Pub/Sub, dedup by seq)
  <──── SSE ────────────┘
```

The critical ordering -- subscribe first, read second -- prevents a race condition where events published during the List read would be missed. Any event seen during catch-up (from the List) that also arrives via Pub/Sub is deduplicated by its sequence number.

### 2.3 Strategy 2: Checkpointer-Only Catch-Up

Events are published to Pub/Sub only (no List persistence). On reconnect, the system reads the LangGraph MemorySaver checkpointer state and reconstructs synthetic AG-UI events (progress status, state snapshot) from it.

**Reconnection (Connect):**

```
CopilotKit ─POST─> /api/v1/stateful-segment
  ^                      |
  |                 1. Subscribe Pub/Sub (buffer live events)
  |                 2. Read checkpointer state (MemorySaver)
  |                 3. Yield synthetic catch-up events (from state)
  |                 4. Yield live events (from Pub/Sub)
  <──── SSE ─────────────┘
```

The tradeoff: catch-up is lower fidelity (the client jumps to the current state rather than seeing a fast-forward replay), but the implementation is simpler and uses less Redis storage.

### 2.4 CopilotKit Integration Flow

CopilotKit uses two request types communicated via `metadata.requestType`:

| Scenario | requestType | Backend Action |
|----------|-------------|----------------|
| User sends new query | `chat` | Start background agent task, stream via Pub/Sub |
| CopilotKit re-sends same query | `chat` | Duplicate detected, return state snapshot |
| Browser reload / new tab | `connect` | Catch-up + bridge to live |
| Completed run reload | `connect` | Replay segment state from checkpointer |

CopilotKit's JSON-RPC protocol wraps requests as `agent/chat` or `agent/connect` methods. The CopilotRuntime proxy translates these into standard HTTP POST requests with the appropriate `requestType` in the metadata.

### 2.5 Duplicate-Query Prevention

CopilotKit re-sends the full messages array after each run completes. Without protection, this creates an infinite re-run loop. The backend detects duplicates by comparing the last human message in the incoming request against the last human message stored in the checkpointer:

```
CopilotKit ─── POST (messages=[...]) ──> Backend
     ^                                      |
     |                                      |── Compare last human message
     |                                      |   with checkpointer state
     |                                      |
     |    (same query already processed)    |
     |<── RUN_STARTED + STATE_SNAPSHOT ─────|  <── replay segment state
     |<── RUN_FINISHED ─────────────────────|
```

The `STATE_SNAPSHOT` in the duplicate response is critical: `RUN_STARTED` resets CopilotKit's co-agent state, so without replaying the segment data, the segment card would vanish from the UI.

---

## 3. Root Configuration Files

### 3.1 pyproject.toml

**Path:** `pyproject.toml`

Defines the Python project metadata and dependencies using the PEP 621 format with Hatch as the build backend.

```toml
[project]
name = "stream-reconnection-demo"
version = "0.1.0"
description = "AG-UI stream reconnection POC using Redis Streams"
requires-python = ">=3.13"
dependencies = [
    "ag-ui-protocol>=0.1.14",
    "langgraph>=0.4.1",
    "langchain-anthropic>=0.4.4",
    "langchain-core>=0.3.59",
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "pydantic>=2.11.0",
    "redis[hiredis]>=5.0.0",
]
```

Key dependencies:
- **ag-ui-protocol**: Provides the AG-UI event types (`RunStartedEvent`, `StateSnapshotEvent`, etc.) and the `EventEncoder` that serializes them to SSE format.
- **langgraph + langchain-anthropic**: The agent pipeline framework and Claude LLM integration.
- **fastapi + uvicorn**: The async HTTP server.
- **redis[hiredis]**: Async Redis client with the C-accelerated parser for performance.

The wheel is built from `src/stream_reconnection_demo` via Hatch.

### 3.2 justfile

**Path:** `justfile`

Task runner with commands for dependency installation, running services, and code quality:

```just
redis:
    podman run --rm --name redis-reconnect -p 6379:6379 docker.io/redis:7-alpine

backend:
    uv run python -m stream_reconnection_demo.main

frontend:
    cd frontend && npm run dev

frontend-next:
    cd frontend-next && npm run dev
```

The `prepare` and `prepare-next` recipes install both backend (`uv sync`) and frontend (`npm install`) dependencies in one command. There are separate commands for the two frontend variants.

### 3.3 .gitignore

**Path:** `.gitignore`

Excludes `__pycache__/`, `.venv/`, `.env`, `node_modules/`, `.next/`, `dist/`, and build artifacts. Keeps the repository clean of generated files and secrets.

---

## 4. Backend (Python)

All backend code lives under `src/stream_reconnection_demo/`.

### 4.1 Entry Point: main.py

**Path:** `src/stream_reconnection_demo/main.py`

Creates the FastAPI application, initializes shared resources during startup, and registers route handlers.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build agent graph with MemorySaver checkpointer
    checkpointer = MemorySaver()
    app.state.segment_graph = build_segment_graph(checkpointer=checkpointer)

    # Build a separate graph for stateful-segment (own checkpointer namespace)
    stateful_checkpointer = MemorySaver()
    app.state.stateful_segment_graph = build_segment_graph(checkpointer=stateful_checkpointer)

    # Initialize Redis Pub/Sub manager
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    app.state.pubsub = RedisPubSubManager(redis_url)

    yield

    await app.state.pubsub.close()
```

**Key design decisions:**

- **Two separate LangGraph graphs** with independent `MemorySaver` checkpointers. This prevents the two strategies from interfering with each other's state. Each stores its own thread history independently.
- **Shared resources on `app.state`**: The `segment_graph`, `stateful_segment_graph`, and `pubsub` manager are attached to `app.state` so route handlers can access them via `request.app.state`.
- **CORS configured wide open** (`allow_origins=["*"]`) for development.

The app exposes three logical endpoints:
- `POST /api/v1/segment` -- Strategy 1 (Pub/Sub + List)
- `POST /api/v1/stateful-segment` -- Strategy 2 (Checkpointer-only)
- `GET /health` -- Simple health check returning `{"status": "ok"}`

The server runs on `0.0.0.0:8000` with hot reload enabled.

### 4.2 Schemas

#### 4.2.1 schemas/segment.py

**Path:** `src/stream_reconnection_demo/schemas/segment.py`

Three Pydantic models define the structured output of the segment pipeline:

```python
class Condition(BaseModel):
    field: str
    operator: str
    value: str | int | float | list[str]

class ConditionGroup(BaseModel):
    logical_operator: Literal["AND", "OR"]
    conditions: list[Condition]

class Segment(BaseModel):
    name: str
    description: str
    condition_groups: list[ConditionGroup]
    estimated_scope: str | None = None
```

A `Segment` has a human-readable name, description, one or more `ConditionGroup`s (each with AND/OR logic containing filter conditions), and an optional scope estimate string.

Example segment JSON:
```json
{
  "name": "US Purchasers (Last 30 Days)",
  "description": "Users from the United States who signed up in the last 30 days and made at least one purchase",
  "condition_groups": [
    {
      "logical_operator": "AND",
      "conditions": [
        { "field": "country", "operator": "equals", "value": "US" },
        { "field": "signup_date", "operator": "within_last", "value": "30 days" },
        { "field": "purchase_count", "operator": "greater_than", "value": 0 }
      ]
    }
  ],
  "estimated_scope": "Moderate audience -- balanced between reach and specificity (3 conditions active)"
}
```

The `Segment` model is used by `ChatAnthropic.with_structured_output(Segment)` in the final pipeline node to force Claude to produce structured JSON matching this schema.

### 4.3 Core Infrastructure

#### 4.3.1 core/events.py

**Path:** `src/stream_reconnection_demo/core/events.py`

Provides two utility functions and the `EventEmitter` class.

**Utility functions:**

```python
def get_field(body: dict, snake: str, camel: str, default=None) -> Any:
    """Return a value trying snake_case first, then camelCase."""
    if snake in body: return body[snake]
    if camel in body: return body[camel]
    return default
```

This handles the field naming mismatch between CopilotKit (which sends `threadId`, `runId` in camelCase) and Python conventions (`thread_id`, `run_id`).

```python
def extract_user_query(messages: list[dict]) -> str:
    """Return the text content of the last user message."""
    for msg in reversed(messages):
        if msg.get("role") != "user": continue
        content = msg.get("content", "")
        if isinstance(content, str): return content
        if isinstance(content, list):
            parts = [part["text"] for part in content
                     if isinstance(part, dict) and part.get("type") == "text"]
            return "\n".join(parts)
    return ""
```

Handles both plain string content and list-of-parts content (the AG-UI protocol can send messages as arrays of typed content blocks).

**EventEmitter class:**

A thin wrapper around the AG-UI `EventEncoder` with typed helper methods for every event type. Each `emit_*` method constructs the corresponding AG-UI event object and returns the SSE-encoded string (`data: {json}\n\n`).

```python
class EventEmitter:
    def __init__(self):
        self._encoder = EventEncoder()

    def emit_run_started(self, thread_id: str, run_id: str) -> str:
        return self._encoder.encode(RunStartedEvent(thread_id=thread_id, run_id=run_id))

    def emit_state_snapshot(self, snapshot: dict) -> str:
        return self._encoder.encode(StateSnapshotEvent(snapshot=snapshot))

    def emit_tool_call_start(self, tool_call_id: str, tool_call_name: str, ...) -> str:
        return self._encoder.encode(ToolCallStartEvent(...))

    # ... emit_step_start, emit_step_finish, emit_text_start/content/end,
    #     emit_state_delta, emit_activity_snapshot, emit_reasoning_*,
    #     emit_tool_call_args/end, emit_run_finished, emit_run_error,
    #     emit_messages_snapshot, emit_custom
```

The class also provides `langchain_messages_to_agui()` which converts LangChain message objects (`HumanMessage`, `AIMessage`) to AG-UI format for `MESSAGES_SNAPSHOT` events. This is used during reconnection to restore chat history.

AG-UI events emitted by this project:

| Event Type | Purpose |
|-----------|---------|
| `RUN_STARTED` | Marks the beginning of a pipeline run |
| `RUN_FINISHED` | Marks completion |
| `RUN_ERROR` | Reports pipeline errors |
| `STEP_STARTED` / `STEP_FINISHED` | Wraps each pipeline node |
| `TOOL_CALL_START` / `TOOL_CALL_ARGS` / `TOOL_CALL_END` | Sends progress updates to `update_progress_status` action |
| `ACTIVITY_SNAPSHOT` | Sends processing progress bar data |
| `REASONING_START` / `REASONING_MESSAGE_*` / `REASONING_END` | Chain-of-thought display |
| `STATE_SNAPSHOT` | Full co-agent state (the segment result) |
| `STATE_DELTA` | Incremental state updates (intermediate node outputs) |
| `TEXT_MESSAGE_START` / `TEXT_MESSAGE_CONTENT` / `TEXT_MESSAGE_END` | Final assistant text message |
| `MESSAGES_SNAPSHOT` | Chat history restoration on reconnect |

#### 4.3.2 core/pubsub.py

**Path:** `src/stream_reconnection_demo/core/pubsub.py`

The `RedisPubSubManager` class manages all Redis interactions for event streaming and persistence. It uses four Redis key patterns:

| Key Pattern | Redis Type | Purpose | TTL |
|-------------|-----------|---------|-----|
| `agent:{thread_id}:{run_id}` | Pub/Sub channel | Live event streaming | N/A |
| `events:{thread_id}:{run_id}` | List | Event buffer for catch-up | 1 hour |
| `active_run:{thread_id}` | String | Maps thread to current run_id | 1 hour |
| `run_status:{thread_id}:{run_id}` | String | `running` / `completed` / `error` | 1 hour |

**Run lifecycle methods:**

```python
async def start_run(self, thread_id: str, run_id: str) -> None:
    pipe = self._redis.pipeline()
    pipe.set(self._active_run_key(thread_id), run_id, ex=KEY_TTL)
    pipe.set(self._run_status_key(thread_id, run_id), "running", ex=KEY_TTL)
    await pipe.execute()

async def complete_run(self, thread_id: str, run_id: str) -> None:
    pipe = self._redis.pipeline()
    pipe.set(self._run_status_key(thread_id, run_id), "completed", ex=KEY_TTL)
    pipe.delete(self._active_run_key(thread_id))
    await pipe.execute()
    await self._redis.publish(self._channel_key(thread_id, run_id), STREAM_END)
```

`start_run` sets the active run pointer and marks status as `running`. `complete_run` updates status, removes the active pointer, then publishes a `STREAM_END` sentinel. The sentinel goes after the state update so subscribers see a consistent state when they terminate.

**Event publishing:**

```python
async def publish_event(self, thread_id: str, run_id: str, event_data: str) -> int:
    events_key = self._events_key(thread_id, run_id)
    seq: int = await self._redis.rpush(events_key, event_data)
    await self._redis.expire(events_key, KEY_TTL)
    envelope = json.dumps({"seq": seq, "event": event_data})
    await self._redis.publish(self._channel_key(thread_id, run_id), envelope)
    return seq
```

`RPUSH` returns the new list length, which is the 1-based sequence number. This sequence is included in the Pub/Sub envelope so subscribers can deduplicate. The List gets a TTL on every push (idempotent via `expire`).

**The race-condition-safe catch-up algorithm (`catch_up_and_follow`):**

```python
async def catch_up_and_follow(self, thread_id, run_id) -> AsyncIterator[str]:
    # Step 1: Subscribe FIRST (buffer any live events)
    pubsub = self._redis.pubsub()
    await pubsub.subscribe(channel_name)

    try:
        # Step 2: Read all persisted events from List
        events = await self.read_events(thread_id, run_id)
        seen_seq = 0
        for event_data in events:
            seen_seq += 1
            yield event_data

        # Early exit if run already completed
        status = await self.get_run_status(thread_id, run_id)
        if status in ("completed", "error"):
            return

        # Step 3: Follow live events, dedup by seq
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if msg is None:
                # Timeout -- check if run is still alive
                status = await self.get_run_status(thread_id, run_id)
                if status in ("completed", "error", None):
                    # Final drain from List
                    remaining = await self._redis.lrange(events_key, seen_seq, -1)
                    for event_data in remaining:
                        seen_seq += 1
                        yield event_data
                    return
                continue

            if raw in (STREAM_END, STREAM_ERROR):
                # Final drain from List before exiting
                remaining = await self._redis.lrange(events_key, seen_seq, -1)
                for event_data in remaining:
                    seen_seq += 1
                    yield event_data
                return

            envelope = json.loads(raw)
            seq = envelope.get("seq", 0)
            if seq <= seen_seq:
                continue  # Already yielded during catch-up
            seen_seq = seq
            yield envelope["event"]
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.aclose()
```

The algorithm has three safety mechanisms:
1. **Subscribe-before-read ordering** prevents events from being missed during the List read.
2. **Sequence-based deduplication** (`seq <= seen_seq`) prevents events from being yielded twice.
3. **Final drain on sentinel/timeout** catches events that were `RPUSH`ed right before the sentinel was published.

#### 4.3.3 core/agent_runner.py

**Path:** `src/stream_reconnection_demo/core/agent_runner.py`

Manages background asyncio tasks for running the agent pipeline. Contains two variants:

**Strategy 1: `run_agent_background` / `start_agent_task`**

Iterates over the AG-UI event stream and publishes each event to both Redis Pub/Sub and the event List via `pubsub.publish_event()`:

```python
async def run_agent_background(pubsub, segment_graph, thread_id, run_id, event_stream):
    try:
        async for event_sse in event_stream:
            await pubsub.publish_event(thread_id, run_id, event_sse)
        await pubsub.complete_run(thread_id, run_id)
    except Exception as e:
        await pubsub.error_run(thread_id, run_id, str(e))
    finally:
        _running_tasks.pop(run_id, None)
```

**Strategy 2: `run_agent_pubsub_only` / `start_agent_task_pubsub_only`**

Same structure but publishes to Pub/Sub only (no List persistence):

```python
async def run_agent_pubsub_only(pubsub, segment_graph, thread_id, run_id, event_stream):
    try:
        async for event_sse in event_stream:
            channel_key = pubsub._channel_key(thread_id, run_id)
            message = json.dumps({"seq": 0, "event": event_sse})
            await pubsub._redis.publish(channel_key, message)
        await pubsub.complete_run(thread_id, run_id)
    except Exception as e:
        await pubsub.error_run(thread_id, run_id, str(e))
    finally:
        _running_tasks.pop(run_id, None)
```

Note: `seq` is always `0` in the Pub/Sub-only variant since there is no List to provide sequence numbers. This is fine because this strategy does not use sequence-based deduplication.

Both variants use `asyncio.create_task()` and register tasks in a module-level `_running_tasks` dict for tracking. The `is_agent_running()` function checks this registry.

#### 4.3.4 core/middleware.py

**Path:** `src/stream_reconnection_demo/core/middleware.py`

A simple logging middleware for AG-UI event streams:

```python
class LoggingMiddleware:
    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        async for event in event_stream:
            parsed = _parse_sse_event(event)
            if parsed is not None:
                event_type = parsed.get("type", "UNKNOWN")
                logger.info("AG-UI event: %s", event_type)
            yield event
```

The `_parse_sse_event` helper extracts JSON from SSE-formatted strings (`data: {json}\n\n`). This middleware is imported by the stateful-segment routes but the main streaming paths do not currently use it inline.

### 4.4 Agent: Segment Pipeline

#### 4.4.1 agent/segment/state.py

**Path:** `src/stream_reconnection_demo/agent/segment/state.py`

Defines the LangGraph state schema as a `TypedDict`:

```python
class SegmentAgentState(TypedDict):
    messages: Annotated[list, add]      # Chat history (append-only via add reducer)
    segment: Segment | None             # Final segment output
    error: str | None                   # Error message if pipeline fails
    current_node: str                   # Name of the last completed node
    requirements: str | None            # from analyze_requirements
    entities: list                      # from extract_entities
    validated_fields: list              # from validate_fields
    operator_mappings: list             # from map_operators
    conditions_draft: list              # from generate_conditions
    optimized_conditions: list          # from optimize_conditions
    scope_estimate: str | None          # from estimate_scope
```

The `messages` field uses `Annotated[list, add]` -- LangGraph's reducer pattern that appends new messages rather than replacing the list. Each node writes to its specific fields, and the state accumulates data as the pipeline progresses.

#### 4.4.2 agent/segment/graph.py

**Path:** `src/stream_reconnection_demo/agent/segment/graph.py`

Defines the 8-node LangGraph pipeline. The nodes execute sequentially in a linear chain:

```
START -> analyze_requirements -> extract_entities -> validate_fields ->
         map_operators -> generate_conditions -> optimize_conditions ->
         estimate_scope -> build_segment -> END
```

**Nodes 0-6: Deterministic processing with simulated latency**

Each of the first 7 nodes follows the same pattern: `await asyncio.sleep(8-10)` (simulating processing), then perform deterministic analysis:

```python
async def analyze_requirements(state: SegmentAgentState) -> dict:
    """Node 0: Parse user query into structured requirements."""
    await asyncio.sleep(8)

    # Extract query from messages
    query = ""
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content"):
            query = msg.content
            break

    # Keyword extraction using KEYWORD_FIELD_MAP
    words = re.findall(r'\b\w+\b', query.lower())
    detected_intents = []
    for word in words:
        if word in KEYWORD_FIELD_MAP:
            field = KEYWORD_FIELD_MAP[word]
            detected_intents.append(f"{word} -> {field}")

    return {
        "current_node": "analyze_requirements",
        "requirements": f"Query: {query}\nDetected intents: {', '.join(detected_intents)}...",
    }
```

The `KEYWORD_FIELD_MAP` maps natural language keywords to field names:
```python
KEYWORD_FIELD_MAP = {
    "us": "country", "usa": "country", "united states": "country",
    "purchase": "purchase_count", "bought": "purchase_count",
    "signup": "signup_date", "signed up": "signup_date",
    "login": "login_count", "active": "last_login_date",
    # ... 25+ keyword-to-field mappings
}
```

The other deterministic nodes follow a similar pattern:
- **`extract_entities`** (Node 1): Groups detected fields into categories (location, temporal, behavioral, demographic, engagement, account).
- **`validate_fields`** (Node 2): Cross-references detected keywords against the `AVAILABLE_FIELDS` set of valid field names.
- **`map_operators`** (Node 3): Assigns operators based on field type (categorical fields get `equals`, temporal get `within_last`, numeric get `greater_than`).
- **`generate_conditions`** (Node 4): Builds draft condition structures from operator mappings with value hints.
- **`optimize_conditions`** (Node 5): Deduplicates conditions by field name.
- **`estimate_scope`** (Node 6): Provides a rough audience size estimate based on condition count.

**Node 7: `build_segment` -- actual LLM call**

The final node is the only one that calls Claude. It uses `ChatAnthropic.with_structured_output(Segment)` to force structured JSON output:

```python
def _build_segment_node(llm: ChatAnthropic):
    structured_llm = llm.with_structured_output(Segment)

    async def build_segment(state: SegmentAgentState) -> dict:
        # Gather all pre-analyzed context
        enriched_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"## Pre-analyzed Context\n"
            f"Requirements: {state.get('requirements', '')}\n"
            f"Entities: {state.get('entities', [])}\n"
            f"Validated fields: {', '.join(state.get('validated_fields', []))}\n"
            # ... all intermediate results
        )

        messages = [
            SystemMessage(content=enriched_prompt),
            HumanMessage(content=query),
        ]
        result = await structured_llm.ainvoke(messages)
        summary = f"Created segment: **{result.name}**\n\n{result.description}"
        return {
            "current_node": "build_segment",
            "segment": result,
            "messages": [AIMessage(content=summary)],
        }

    return build_segment
```

The `SYSTEM_PROMPT` defines the LLM's role as a segmentation expert, lists available fields and operators, and provides formatting rules.

**Graph compilation:**

```python
def build_segment_graph(model="claude-sonnet-4-20250514", checkpointer=None):
    llm = ChatAnthropic(model=model)
    graph = StateGraph(SegmentAgentState)

    # Add all 8 nodes
    graph.add_node("analyze_requirements", analyze_requirements)
    # ... 6 more nodes ...
    graph.add_node("build_segment", _build_segment_node(llm))

    # Linear chain: START -> node0 -> node1 -> ... -> node7 -> END
    graph.add_edge(START, "analyze_requirements")
    graph.add_edge("analyze_requirements", "extract_entities")
    # ... 6 more edges ...
    graph.add_edge("build_segment", END)

    return graph.compile(checkpointer=checkpointer)
```

#### 4.4.3 agent/segment/routes.py

**Path:** `src/stream_reconnection_demo/agent/segment/routes.py`

The most complex file in the backend. Defines the `POST /api/v1/segment` endpoint and the event-streaming pipeline orchestration.

**NODE_META: Per-node metadata**

Each of the 8 pipeline nodes has a metadata dictionary that drives the AG-UI events:

```python
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
    # ... 7 more entries, with progress values:
    # 0.10, 0.20, 0.30, 0.45, 0.55, 0.70, 0.85, 0.95
}
```

**`run_segment_pipeline()`: The event-streaming generator**

This async generator orchestrates LangGraph execution and yields AG-UI events:

```python
async def run_segment_pipeline(segment_graph, query, thread_id, run_id) -> AsyncIterator[str]:
    message_id = str(uuid.uuid4())

    # 1. Run lifecycle start
    yield emitter.emit_run_started(thread_id, run_id)
    yield emitter.emit_state_snapshot({})  # Clear old segment card

    # 2. Reset progress bar
    yield emitter.emit_tool_call_start(reset_tool_id, "update_progress_status", message_id)
    yield emitter.emit_tool_call_args(reset_tool_id, json.dumps({
        "status": "starting", "node": "", "node_index": -1, "total_nodes": 8
    }))
    yield emitter.emit_tool_call_end(reset_tool_id)

    # 3. Stream LangGraph execution
    async for chunk in segment_graph.astream(graph_input, config=config, stream_mode="updates"):
        for node_name, node_output in chunk.items():
            meta = NODE_META[node_name]

            yield emitter.emit_step_start(node_name)

            # Progress tool call
            yield emitter.emit_tool_call_start(tool_call_id, "update_progress_status", message_id)
            yield emitter.emit_tool_call_args(tool_call_id, json.dumps({
                "status": meta["status"], "node": node_name,
                "node_index": meta["index"], "total_nodes": TOTAL_NODES,
            }))
            yield emitter.emit_tool_call_end(tool_call_id)

            # Activity snapshot (progress bar)
            yield emitter.emit_activity_snapshot(activity_id, "processing", {
                "title": meta["title"], "progress": meta["progress"], "details": meta["details"],
            })

            # Reasoning chain (3 steps per node)
            yield emitter.emit_reasoning_start(reasoning_id)
            yield emitter.emit_reasoning_message_start(reasoning_id)
            for step in meta["reasoning"]:
                yield emitter.emit_reasoning_content(reasoning_id, step)
            yield emitter.emit_reasoning_message_end(reasoning_id)
            yield emitter.emit_reasoning_end(reasoning_id)

            # State deltas for intermediate results
            for field_name in _DELTA_FIELDS:
                if field_name in node_output and node_output[field_name]:
                    delta_ops.append({"op": "add", "path": f"/{field_name}", "value": node_output[field_name]})
            if delta_ops:
                yield emitter.emit_state_delta(delta_ops)

            yield emitter.emit_step_finish(node_name)

    # 4. Final events
    yield emitter.emit_state_snapshot(segment_dict)  # Full segment data
    yield emitter.emit_text_start(message_id, "assistant")
    yield emitter.emit_text_content(message_id, summary)
    yield emitter.emit_text_end(message_id)
    yield emitter.emit_run_finished(thread_id, run_id)
```

Each node produces this event sequence:
```
STEP_STARTED
  TOOL_CALL_START  (update_progress_status)
  TOOL_CALL_ARGS   {"status":"analyzing","node":"analyze_requirements","node_index":0,"total_nodes":8}
  TOOL_CALL_END
  ACTIVITY_SNAPSHOT {"title":"Analyzing Requirements","progress":0.10,"details":"..."}
  REASONING_START
  REASONING_MESSAGE_START
  REASONING_MESSAGE_CONTENT (x3 reasoning steps)
  REASONING_MESSAGE_END
  REASONING_END
  STATE_DELTA      [{"op":"add","path":"/requirements","value":{...}}]
STEP_FINISHED
```

**Intent-based request handlers:**

The `POST /api/v1/segment` endpoint (`generate_segment`) parses the request and dispatches to the appropriate handler:

```python
@router.post("/segment")
async def generate_segment(request: Request):
    body = await request.json()
    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    query = extract_user_query(body.get("messages", []))

    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    if request_type == "connect":
        return await _handle_connect(pubsub, segment_graph, thread_id, run_id)
    return await _handle_chat(pubsub, segment_graph, thread_id, run_id, query)
```

**`_handle_chat()` logic:**

1. If the query is empty, delegates to `_handle_connect()` (handles CopilotKit sending empty messages on reload).
2. Checks if this query was already processed by comparing against the checkpointer's last human message. If duplicate, returns `RUN_STARTED + STATE_SNAPSHOT + RUN_FINISHED` (minimal response that satisfies CopilotKit without re-running the pipeline).
3. Otherwise, registers the run in Redis, starts the pipeline as a background task, waits 100ms for events to start publishing, then returns `pubsub.catch_up_and_follow()` as a streaming response.

**`_handle_connect()` logic:**

1. Checks for an active run in Redis. If found, uses `pubsub.catch_up_and_follow()` to stream catch-up events plus live events. Injects a `MESSAGES_SNAPSHOT` after `RUN_STARTED` to restore chat history.
2. If no active run, checks the checkpointer for completed state. If found, replays it as synthetic events: `RUN_STARTED`, `MESSAGES_SNAPSHOT`, `STATE_SNAPSHOT`, progress tool call (completed), `RUN_FINISHED`.
3. If nothing found, returns an empty run (`RUN_STARTED` + `RUN_FINISHED`).

**State endpoint:**

```python
@router.get("/segment/state/{thread_id}")
async def get_segment_state(thread_id: str, request: Request):
    """Return current segment state from checkpointer for a given thread."""
```

A REST endpoint that returns the segment state directly (not SSE). Used by the frontend as a fallback when CopilotKit does not forward `agent/connect` to the backend.

### 4.5 Agent: Stateful Segment Pipeline

#### 4.5.1 agent/stateful_segment/routes.py

**Path:** `src/stream_reconnection_demo/agent/stateful_segment/routes.py`

Implements Strategy 2 -- same pipeline, different reconnection. Duplicates `NODE_META` from `segment/routes.py` and adds:

**`NODE_STATE_FIELDS`: Maps nodes to their state fields**

```python
NODE_STATE_FIELDS = {
    "analyze_requirements": "requirements",
    "extract_entities": "entities",
    "validate_fields": "validated_fields",
    "map_operators": "operator_mappings",
    "generate_conditions": "conditions_draft",
    "optimize_conditions": "optimized_conditions",
    "estimate_scope": "scope_estimate",
    "build_segment": "segment",
}
```

Used by `_reconstruct_progress_from_state()` to determine which nodes have completed by checking which state fields are populated:

```python
def _reconstruct_progress_from_state(state: dict) -> tuple[str | None, int]:
    last_completed = None
    completed_count = 0
    for node_name in NODE_ORDER:
        field = NODE_STATE_FIELDS.get(node_name)
        if field and state.get(field):
            last_completed = node_name
            completed_count += 1
        else:
            break
    return last_completed, completed_count
```

**`_emit_synthetic_catchup()`: Reconstruct AG-UI events from state**

```python
async def _emit_synthetic_catchup(state, thread_id, run_id) -> AsyncIterator[str]:
    yield emitter.emit_run_started(thread_id, run_id)

    # Restore chat history
    messages = state.get("messages", [])
    if messages:
        agui_msgs = emitter.langchain_messages_to_agui(messages)
        yield emitter.emit_messages_snapshot(agui_msgs)

    # Emit progress status for the last completed node
    last_node, completed_count = _reconstruct_progress_from_state(state)
    if last_node:
        meta = NODE_META[last_node]
        yield emitter.emit_tool_call_start(tool_call_id, "update_progress_status", message_id)
        yield emitter.emit_tool_call_args(tool_call_id, json.dumps({
            "status": meta["status"], "node": last_node,
            "node_index": meta["index"], "total_nodes": TOTAL_NODES,
        }))
        yield emitter.emit_tool_call_end(tool_call_id)

    # Emit segment state if pipeline completed
    segment = state.get("segment")
    if segment:
        yield emitter.emit_state_snapshot(seg_dict)
```

This produces a condensed version of the full event stream -- just enough for the frontend to reconstruct its UI state.

**`_handle_stateful_connect()`: Live + synthetic catch-up**

When an active run exists:
1. Subscribe to the Pub/Sub channel.
2. Read checkpointer state and emit synthetic catch-up events.
3. Forward live events from Pub/Sub.
4. On run completion, read final state from checkpointer for the segment result.

When no active run but checkpointer has state:
- Emit synthetic catch-up events + `RUN_FINISHED`.

**`_handle_stateful_chat()`: New run with Pub/Sub-only streaming**

1. Checks for duplicate query (same as Strategy 1).
2. Starts the pipeline via `start_agent_task_pubsub_only()` (no List persistence).
3. Streams live events via `pubsub.subscribe_and_stream()` (no catch-up, since the client is connected from the start).

---

## 5. Frontend: React + Webpack

The primary frontend implementation. Uses CopilotKit embedded directly in the webpack dev server.

### 5.1 Configuration

#### 5.1.1 package.json

**Path:** `frontend/package.json`

```json
{
  "dependencies": {
    "@copilotkit/react-core": "^1.8.16",
    "@copilotkit/react-ui": "^1.8.16",
    "@copilotkit/runtime-client-gql": "^1.8.16",
    "react": "^19.1.0",
    "react-dom": "^19.1.0"
  },
  "devDependencies": {
    "@copilotkit/runtime": "^1.8.16",
    // webpack, ts-loader, tailwindcss, postcss
  }
}
```

Note: `@copilotkit/runtime` is a devDependency because it runs inside the webpack dev server (not in the browser bundle).

#### 5.1.2 webpack.config.js

**Path:** `frontend/webpack.config.js`

The most unusual file in the frontend. Beyond standard webpack configuration, it embeds two CopilotRuntime instances inside the webpack dev server using `setupMiddlewares`:

```javascript
devServer: {
  port: 3000,
  setupMiddlewares: (middlewares, devServer) => {
    (async () => {
      const { CopilotRuntime, copilotRuntimeNodeHttpEndpoint, EmptyAdapter } =
        await import("@copilotkit/runtime");
      const { LangGraphHttpAgent } = await import("@copilotkit/runtime/langgraph");

      const runtime = new CopilotRuntime({
        agents: {
          default: new LangGraphHttpAgent({
            url: `${backendUrl}/api/v1/segment`,
            description: "Segment generation agent",
          }),
        },
      });

      const handler = copilotRuntimeNodeHttpEndpoint({
        runtime,
        serviceAdapter: new EmptyAdapter(),
        endpoint: "/copilotkit",
      });

      devServer.app.all("/copilotkit", async (req, res) => {
        // Parse body to detect agent/connect
        const parsed = JSON.parse(rawBody);

        if (parsed.method === "agent/connect") {
          // Proxy directly to backend -- CopilotKit's in-memory runner
          // loses state on page reload
          const backendResp = await fetch(`${backendUrl}/api/v1/segment`, {
            method: "POST",
            body: JSON.stringify({
              thread_id: threadId,
              run_id: runId,
              messages: parsed.body?.messages ?? [],
              metadata: { requestType: "connect" },
            }),
          });
          // Stream SSE response back
          res.writeHead(backendResp.status, {
            "Content-Type": "text/event-stream",
          });
          const reader = backendResp.body.getReader();
          while (true) {
            const { done, value } = await reader.read();
            if (done) { res.end(); return; }
            res.write(value);
          }
        }

        // Not agent/connect -- pass to CopilotKit handler
        req.body = parsed;
        await handler(req, res);
      });
    })();
    return middlewares;
  },
}
```

The critical detail: `agent/connect` requests are intercepted and proxied directly to the backend instead of being handled by CopilotKit's built-in `InMemoryAgentRunner`. This is necessary because CopilotKit's in-memory runner loses state on page reload -- only the backend (with Redis and checkpointer) has the real state.

Two endpoints are registered:
- `/copilotkit` -> `http://localhost:8000/api/v1/segment`
- `/copilotkit-stateful` -> `http://localhost:8000/api/v1/stateful-segment`

The `fast-json-patch` alias resolves a CJS/ESM compatibility issue:
```javascript
resolve: {
  alias: {
    "fast-json-patch": path.resolve(__dirname, "node_modules/fast-json-patch/index.js"),
  },
},
```

### 5.2 Entry Point & App Shell

#### 5.2.1 src/index.tsx

**Path:** `frontend/src/index.tsx`

```typescript
// Prevent "already defined" errors for custom elements during HMR
const origDefine = customElements.define.bind(customElements);
customElements.define = (name, ctor, options?) => {
  if (!customElements.get(name)) origDefine(name, ctor, options);
};

import { createRoot } from "react-dom/client";
import App from "./App";
import "./globals.css";

const root = createRoot(document.getElementById("root")!);
root.render(<App />);
```

The custom elements guard prevents `NotSupportedError` during webpack HMR when CopilotKit's web components are re-registered.

#### 5.2.2 src/App.tsx

**Path:** `frontend/src/App.tsx`

The main application file. It has four key sections:

**1. Runtime URL selection:**

```typescript
const isStatefulMode = window.location.pathname.includes("stateful");
const COPILOT_RUNTIME_URL = isStatefulMode
  ? (process.env.COPILOT_STATEFUL_RUNTIME_URL || "/copilotkit-stateful")
  : (process.env.COPILOT_RUNTIME_URL || "/copilotkit");
```

If the URL path contains "stateful", the app connects to the stateful-segment endpoint. Otherwise, it uses the standard segment endpoint.

**2. `InlineSegmentCard` component:**

```typescript
function InlineSegmentCard() {
  const { state: segment } = useCoAgent<Segment>({ name: "default" });
  if (!segment?.condition_groups) return null;
  return <SegmentCard segment={segment} />;
}
```

Reads co-agent state from CopilotKit's `useCoAgent` hook. Renders the `SegmentCard` only when the segment has `condition_groups` (i.e., the pipeline has completed). This component is placed inline in the chat after the last assistant message.

**3. `CustomRenderMessage`: Custom chat message renderer**

```typescript
function CustomRenderMessage({
  message, messages, inProgress, index, isCurrentMessage,
  AssistantMessage, UserMessage, ImageRenderer,
}: RenderMessageProps) {
  // Reasoning messages: show chain-of-thought panel
  if (message.role === "reasoning" || message.role === "activity") {
    if (!inProgress) return null;
    const fromOldTurn = messages.slice(index + 1).some((m) => m.role === "user");
    if (fromOldTurn) return null;
    const hasNewerOfSameRole = messages.slice(index + 1).some((m) => m.role === message.role);
    if (hasNewerOfSameRole) return null;
    if (message.role === "reasoning") return <ReasoningPanel reasoning={message.content} defaultOpen />;
    return <ActivityIndicator activityType="processing" content={message.content} />;
  }

  // User messages: default rendering
  if (message.role === "user") {
    return <UserMessage key={index} rawData={message} message={message} ImageRenderer={ImageRenderer} />;
  }

  // Assistant messages: with inline segment card
  if (message.role === "assistant") {
    if (!message.content && !(inProgress && isCurrentMessage)) return null;
    const showCard = !!message.content && !messages.slice(index + 1).some(
      (m) => m.role === "assistant" && m.content
    );
    return (
      <>
        <AssistantMessage key={index} rawData={message} message={message}
          isLoading={inProgress && isCurrentMessage && !message.content}
          isGenerating={inProgress && isCurrentMessage && !!message.content}
          isCurrentMessage={isCurrentMessage} />
        {showCard && <InlineSegmentCard />}
      </>
    );
  }
  return null;
}
```

Key rendering logic:
- **Reasoning/activity messages** are only shown during active processing (`inProgress`), and only the most recent one of each role is displayed.
- **Empty assistant messages** (created by CopilotKit re-sends) are hidden.
- **The segment card** is attached only to the last assistant message that has content, preventing duplicate cards.

**4. `SegmentPageContent`: Main content area**

```typescript
function SegmentPageContent() {
  const { state: segment } = useCoAgent<Segment>({ name: "default" });

  // Required for CopilotKit to route STATE_SNAPSHOT events to useCoAgent
  useCoAgentStateRender({ name: "default", render: () => null });

  const [progressStatus, setProgressStatus] = useState(null);

  // Reset progress when co-agent state is cleared (start of new run)
  useEffect(() => {
    if (segment && !segment.condition_groups) {
      setProgressStatus(null);
    }
  }, [segment]);

  // Handle progress updates from backend tool calls
  useCopilotAction({
    name: "update_progress_status",
    parameters: [
      { name: "status", type: "string" },
      { name: "node", type: "string" },
      { name: "node_index", type: "number" },
      { name: "total_nodes", type: "number" },
    ],
    handler: ({ status, node, node_index, total_nodes }) => {
      if (status === "starting") { setProgressStatus(null); return; }
      setProgressStatus({ status, node, nodeIndex: node_index, totalNodes: total_nodes });
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-lg space-y-6">
          {progressStatus && <ProgressStatus {...progressStatus} />}
          {segment?.condition_groups ? (
            <SegmentCard segment={segment} />
          ) : !progressStatus ? (
            <p>Describe your audience in the sidebar to generate a segment.</p>
          ) : null}
        </div>
      </main>
    </div>
  );
}
```

The `useCoAgentStateRender({ name: "default", render: () => null })` call is critical -- without it, CopilotKit does not route `STATE_SNAPSHOT` events to the `useCoAgent` hook. The render function returns `null` because the card is rendered via `InlineSegmentCard` in the custom message renderer instead.

The `useCopilotAction("update_progress_status")` hook receives the backend's `TOOL_CALL_*` events for the `update_progress_status` tool. This is the communication channel between the backend pipeline and the frontend stepper UI.

**5. `App`: Root component with CopilotKit provider**

```typescript
export default function App() {
  const { threadId, ready, startNewThread, switchToThread } = useAgentThread();
  return (
    <>
      {ready ? (
        <CopilotKit key={threadId} runtimeUrl={COPILOT_RUNTIME_URL} threadId={threadId}>
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are a user segmentation assistant..."
            labels={{ title: "Segment Builder", initial: "..." }}
          >
            <SegmentPageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}
```

The `key={threadId}` on `CopilotKit` forces a full re-mount when the thread changes, resetting all CopilotKit state cleanly.

### 5.3 Hooks

#### 5.3.1 hooks/useAgentThread.ts

**Path:** `frontend/src/hooks/useAgentThread.ts`

Manages thread IDs via URL query parameters (`?thread=...`) with browser history support:

```typescript
export function useAgentThread() {
  const [threadFromUrl, setThreadFromUrl] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("thread");
  });

  const generatedId = useRef(crypto.randomUUID());
  const threadId = threadFromUrl || generatedId.current;

  const [mountedThreadId, setMountedThreadId] = useState(threadId);
  const [ready, setReady] = useState(true);

  // When thread changes, briefly unmount CopilotKit for clean re-init
  useEffect(() => {
    if (threadId !== mountedThreadId) {
      setReady(false);
      const timer = setTimeout(() => {
        setMountedThreadId(threadId);
        setReady(true);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [threadId, mountedThreadId]);

  // Set initial URL if no thread param present
  useEffect(() => {
    if (!threadFromUrl) {
      window.history.replaceState(null, "", `${pathname}?thread=${generatedId.current}`);
      setThreadFromUrl(generatedId.current);
    }
  }, [threadFromUrl]);

  // Listen for browser back/forward navigation
  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      setThreadFromUrl(params.get("thread"));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const startNewThread = useCallback(() => { /* push new UUID to history */ }, []);
  const switchToThread = useCallback((id: string) => { /* push specific ID */ }, []);

  return { threadId: mountedThreadId, ready, startNewThread, switchToThread };
}
```

The 150ms `ready` delay between threads prevents CopilotKit from trying to render with stale state. This is the mechanism that enables mid-execution joins by sharing URLs.

### 5.4 Components

#### 5.4.1 components/Nav.tsx

**Path:** `frontend/src/components/Nav.tsx`

Simple navigation header with the app title and a "Segment Builder" label:

```tsx
export function Nav() {
  return (
    <header className="border-b border-gray-200 dark:border-gray-700 px-6 py-3 flex items-center justify-between">
      <a href="/" className="text-lg font-semibold">Stream Reconnection Demo</a>
      <nav className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
        <span className="px-3 py-1.5 rounded-md text-sm font-medium bg-white dark:bg-gray-700 shadow-sm">
          Segment Builder
        </span>
      </nav>
    </header>
  );
}
```

#### 5.4.2 components/SegmentCard.tsx

**Path:** `frontend/src/components/SegmentCard.tsx`

Renders the final segment result as a styled card:

```tsx
export function SegmentCard({ segment }: { segment: Segment }) {
  return (
    <div className="rounded-lg border border-gray-200 ...">
      {/* Header: segment name + "Segment" badge */}
      <div className="px-4 py-3 border-b ...">
        <span className="font-semibold">{segment.name}</span>
        <span className="text-xs bg-purple-100 text-purple-700 ...">Segment</span>
        <p className="text-xs">{segment.description}</p>
      </div>

      {/* Condition groups */}
      <div className="px-4 py-3 space-y-4">
        {segment.condition_groups.map((group, gi) => (
          <div key={gi}>
            {gi > 0 && <div>-- OR --</div>}
            <div>Group {gi + 1} - {group.logical_operator}</div>
            <div className="flex flex-wrap gap-1.5">
              {group.conditions.map((cond, ci) => (
                <span key={ci} className="... font-mono">
                  <span className="text-purple-600">{cond.field}</span>
                  <span className="text-gray-400">{cond.operator}</span>
                  <span>{Array.isArray(cond.value) ? cond.value.join(", ") : String(cond.value)}</span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Scope estimate footer */}
      {segment.estimated_scope && (
        <div className="px-4 py-2 bg-gray-50 ... text-xs">
          Scope: {segment.estimated_scope}
        </div>
      )}
    </div>
  );
}
```

Each condition is rendered as a monospace pill showing `field operator value`. Condition groups are separated by "-- OR --" dividers. Supports dark mode via Tailwind's `dark:` variants.

#### 5.4.3 components/ProgressStatus.tsx

**Path:** `frontend/src/components/ProgressStatus.tsx`

An 8-step visual stepper showing pipeline progress:

```tsx
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

export function ProgressStatus({ status, node, nodeIndex, totalNodes }: ProgressStatusProps) {
  const isCompleted = status === "completed";

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* Status label: "Analyze..." or "Segment Complete" */}
      <div className="flex items-center justify-between mb-2">
        <span>{isCompleted ? "Segment Complete" : `${NODE_LABELS[node]}...`}</span>
        <span>{isCompleted ? `${totalNodes}/${totalNodes}` : `${nodeIndex + 1}/${totalNodes}`}</span>
      </div>

      {/* Stepper circles with connecting lines */}
      <div className="flex items-center gap-1">
        {NODE_ORDER.map((nodeName, i) => {
          let stepState: "completed" | "active" | "pending";
          if (isCompleted || i < nodeIndex) stepState = "completed";
          else if (i === nodeIndex) stepState = "active";
          else stepState = "pending";

          return (
            <div key={nodeName} className="flex-1 flex flex-col items-center">
              {/* Connecting line + circle */}
              <div className="flex items-center w-full">
                {i > 0 && <div className={`flex-1 h-0.5 ${stepState === "pending" ? "bg-gray-200" : "bg-green-500"}`} />}
                <div className={`w-6 h-6 rounded-full ... ${
                  stepState === "completed" ? "bg-green-500" :
                  stepState === "active" ? "bg-blue-500" :
                  "bg-gray-200"
                }`}>
                  {stepState === "completed" ? <Checkmark /> :
                   stepState === "active" ? <PulsingDot /> :
                   <GrayDot />}
                </div>
                {i < totalNodes - 1 && <div className={`flex-1 h-0.5 ...`} />}
              </div>
              {/* Label */}
              <span className="text-[10px]">{NODE_LABELS[nodeName]}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

Completed steps show green checkmarks, the active step shows a pulsing blue dot, and pending steps show gray dots. Connecting lines turn green as steps complete.

#### 5.4.4 components/ActivityIndicator.tsx

**Path:** `frontend/src/components/ActivityIndicator.tsx`

Displays a progress bar in the chat sidebar for the current pipeline step:

```tsx
export function ActivityIndicator({ content }: { activityType: string; content: ActivityContent }) {
  const percentage = Math.round(content.progress * 100);
  return (
    <div className="rounded-lg border border-blue-200 ... p-3 my-2">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
        <span className="text-xs font-medium">{content.title}</span>
        <span className="text-xs ml-auto">{percentage}%</span>
      </div>
      <div className="w-full bg-blue-200 rounded-full h-1.5">
        <div className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
             style={{ width: `${percentage}%` }} />
      </div>
      <p className="text-xs mt-1">{content.details}</p>
    </div>
  );
}
```

Receives `ACTIVITY_SNAPSHOT` events from the backend via CopilotKit's message system. Shows a blue progress bar with a title (e.g., "Analyzing Requirements"), percentage, and details text.

#### 5.4.5 components/ReasoningPanel.tsx

**Path:** `frontend/src/components/ReasoningPanel.tsx`

A collapsible panel showing chain-of-thought reasoning:

```tsx
export function ReasoningPanel({ reasoning, defaultOpen = false }: Props) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  if (!reasoning) return null;
  return (
    <div className="rounded-lg border border-amber-200 ... overflow-hidden">
      <button onClick={() => setIsOpen(!isOpen)}
              className="w-full px-3 py-2 flex items-center gap-2 ...">
        <span className={`transition-transform ${isOpen ? "rotate-90" : ""}`}>&#9654;</span>
        Chain of Thought
      </button>
      {isOpen && (
        <div className="px-3 pb-3 text-xs whitespace-pre-wrap font-mono">
          {reasoning}
        </div>
      )}
    </div>
  );
}
```

Styled in amber/yellow. The triangle rotates 90 degrees when expanded. Content is displayed in monospace font with preserved whitespace.

### 5.5 Types & Styles

#### 5.5.1 lib/types.ts

**Path:** `frontend/src/lib/types.ts`

TypeScript interfaces mirroring the Python Pydantic models:

```typescript
export interface Condition {
  field: string;
  operator: string;
  value: string | number | string[];
}

export interface ConditionGroup {
  logical_operator: "AND" | "OR";
  conditions: Condition[];
}

export interface Segment {
  name: string;
  description: string;
  condition_groups: ConditionGroup[];
  estimated_scope?: string;
}
```

Also defines `ThreadSummary`, `ThreadMessage`, and `ThreadData` interfaces for thread management (used for future features or debugging).

#### 5.5.2 src/globals.css

**Path:** `frontend/src/globals.css`

```css
@import "tailwindcss";
@import "@copilotkit/react-ui/styles.css";

:root {
  --background: #ffffff;
  --foreground: #171717;
}

@media (prefers-color-scheme: dark) {
  :root {
    --background: #0a0a0a;
    --foreground: #ededed;
  }
}

body {
  background: var(--background);
  color: var(--foreground);
  font-family: system-ui, -apple-system, sans-serif;
  margin: 0;
}
```

Imports Tailwind CSS v4 (which uses `@import "tailwindcss"` instead of `@tailwind` directives) and CopilotKit's styles. Sets up CSS variables for light/dark mode.

---

## 6. Frontend: Next.js

The reference frontend implementation using Next.js 15 with the App Router.

### 6.1 Configuration

#### 6.1.1 package.json

**Path:** `frontend-next/package.json`

```json
{
  "dependencies": {
    "@copilotkit/react-core": "^1.8.16",
    "@copilotkit/react-ui": "^1.8.16",
    "@copilotkit/runtime": "^1.8.16",
    "next": "^15.3.3",
    "react": "^19.1.0",
    "react-dom": "^19.1.0"
  }
}
```

Note: `@copilotkit/runtime` is a runtime dependency here (not devDependency) because it runs in the Next.js API routes on the server.

#### 6.1.2 next.config.ts

**Path:** `frontend-next/next.config.ts`

```typescript
const nextConfig: NextConfig = {};
export default nextConfig;
```

No custom configuration needed. PostCSS is configured via `postcss.config.mjs` with `@tailwindcss/postcss`.

### 6.2 App Router Pages

#### 6.2.1 app/layout.tsx

**Path:** `frontend-next/app/layout.tsx`

```tsx
import "./globals.css";
import "@copilotkit/react-ui/styles.css";

export const metadata = {
  title: "AG-UI Stream Reconnection Demo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

The root layout imports CopilotKit styles and provides the HTML shell. In Next.js, CopilotKit styles are imported here rather than in CSS (unlike the webpack version which uses `@import` in CSS).

#### 6.2.2 app/page.tsx

**Path:** `frontend-next/app/page.tsx`

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/segment");
}
```

Immediately redirects `/` to `/segment`. This is a server-side redirect.

#### 6.2.3 app/segment/page.tsx

**Path:** `frontend-next/app/segment/page.tsx`

The segment page for Strategy 1. Nearly identical to the React+Webpack `App.tsx` but adapted for Next.js:

- Uses `"use client"` directive (the entire page is client-rendered).
- Wraps the page content in `<Suspense>` to handle `useSearchParams` (required by Next.js 15).
- Uses `/api/copilotkit/segment` as the runtime URL (Next.js API route instead of webpack proxy).

```tsx
function SegmentPageInner() {
  const { threadId, ready } = useAgentThread();
  return (
    <>
      {ready ? (
        <CopilotKit key={threadId} runtimeUrl="/api/copilotkit/segment" threadId={threadId}>
          <CopilotSidebar defaultOpen={true} RenderMessage={CustomRenderMessage} ...>
            <SegmentPageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function SegmentPage() {
  return <Suspense><SegmentPageInner /></Suspense>;
}
```

The `SegmentPageContent`, `CustomRenderMessage`, and `InlineSegmentCard` components are identical to the React+Webpack versions.

#### 6.2.4 app/stateful-segment/page.tsx

**Path:** `frontend-next/app/stateful-segment/page.tsx`

Identical to `segment/page.tsx` except:
- Uses `/api/copilotkit/stateful-segment` as the runtime URL.
- The sidebar title is "Segment Builder (Stateful)".

### 6.3 API Routes (CopilotRuntime Proxy)

#### 6.3.1 api/copilotkit/segment/route.ts

**Path:** `frontend-next/app/api/copilotkit/segment/route.ts`

The Next.js equivalent of the webpack proxy. Sets up a `CopilotRuntime` with a `LangGraphHttpAgent` pointing to the backend:

```typescript
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const runtime = new CopilotRuntime({
  agents: {
    default: new LangGraphHttpAgent({
      url: `${BACKEND_URL}/api/v1/segment`,
      description: "Segment generation agent",
    }),
  },
});

export const POST = async (req: Request) => {
  const body = await req.json();

  // Intercept agent/connect -- proxy directly to backend
  if (body.method === "agent/connect") {
    const threadId = body.body?.threadId ?? body.params?.threadId;
    const runId = body.body?.runId ?? crypto.randomUUID();

    const backendResp = await fetch(`${BACKEND_URL}/api/v1/segment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: threadId,
        run_id: runId,
        messages: body.body?.messages ?? [],
        metadata: { requestType: "connect" },
      }),
    });

    return new Response(backendResp.body, {
      status: backendResp.status,
      headers: { "Content-Type": "text/event-stream", ... },
    });
  }

  // Non-connect -- pass to CopilotKit handler
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new EmptyAdapter(),
    endpoint: "/api/copilotkit/segment",
  });
  return handleRequest(newReq);
};
```

Same `agent/connect` interception pattern as the webpack version. Uses the `copilotRuntimeNextJSAppRouterEndpoint` helper from CopilotKit instead of `copilotRuntimeNodeHttpEndpoint`.

#### 6.3.2 api/copilotkit/stateful-segment/route.ts

**Path:** `frontend-next/app/api/copilotkit/stateful-segment/route.ts`

Identical structure, pointing to `/api/v1/stateful-segment`.

### 6.4 Shared Components, Hooks, Types

The `frontend-next/components/`, `frontend-next/hooks/`, and `frontend-next/lib/` directories contain the same components as the React+Webpack frontend with minor differences:

| Difference | React+Webpack | Next.js |
|-----------|--------------|---------|
| `Nav.tsx` | Uses `<a href="/">` | Uses `<Link href="/">` from `next/link` |
| Components | No directive needed | Add `"use client"` to `ProgressStatus.tsx`, `ReasoningPanel.tsx` |
| `useAgentThread.ts` | Direct `window.location` access | Guards with `typeof window === "undefined"` for SSR |
| CSS imports | `@import "@copilotkit/react-ui/styles.css"` in CSS | `import` in `layout.tsx` |

All other components (`SegmentCard.tsx`, `ActivityIndicator.tsx`, `ReasoningPanel.tsx`, `ProgressStatus.tsx`) and the `lib/types.ts` file are identical.

---

## 7. End-to-End Request Lifecycle

### 7.1 New Query (Chat Flow)

User types "Users from the US who signed up in the last 30 days and made a purchase" in the CopilotSidebar:

```
Browser                          CopilotKit Runtime                    FastAPI Backend
──────                           ──────────────────                    ──────────────
  |                                    |                                    |
  |── User submits message ──────>    |                                    |
  |                                    |── JSON-RPC: agent/chat ──────────>|
  |                                    |   { method: "agent/chat",         |
  |                                    |     body: { threadId, runId,      |
  |                                    |       messages: [...] } }         |
  |                                    |                                    |
  |                                    |   (CopilotKit translates to:)     |
  |                                    |── POST /api/v1/segment ──────────>|
  |                                    |   { thread_id, run_id,            |
  |                                    |     messages: [...],              |
  |                                    |     metadata: {requestType:"chat"}}|
  |                                    |                                    |
  |                                    |                           generate_segment():
  |                                    |                           1. Parse body, extract query
  |                                    |                           2. Check checkpointer for dup
  |                                    |                           3. pubsub.start_run(thread, run)
  |                                    |                              → Redis SET active_run:{tid}
  |                                    |                              → Redis SET run_status:{tid}:{rid} = "running"
  |                                    |                           4. Create pipeline generator
  |                                    |                           5. start_agent_task() → asyncio bg task
  |                                    |                           6. sleep(0.1)  ← let task start
  |                                    |                           7. Return StreamingResponse(
  |                                    |                                pubsub.catch_up_and_follow())
  |                                    |                                    |
  |                                    |              Background task:      |
  |                                    |              LangGraph astream()   |
  |                                    |                 |                  |
  |                                    |              Node 0: analyze_requirements
  |                                    |                 |  (sleep 8s)      |
  |                                    |                 v                  |
  |                                    |              Yield SSE events:     |
  |                                    |              - STEP_STARTED        |
  |                                    |              - TOOL_CALL_*         |
  |                                    |              - ACTIVITY_SNAPSHOT   |
  |                                    |              - REASONING_*         |
  |                                    |              - STATE_DELTA         |
  |                                    |              - STEP_FINISHED       |
  |                                    |                 |                  |
  |                                    |              Each event:           |
  |                                    |              → RPUSH events:{tid}:{rid}
  |                                    |              → PUBLISH agent:{tid}:{rid}
  |                                    |                 |                  |
  |                                    |<── SSE: events via catch_up_and_follow
  |<── CopilotKit processes events ───|                                    |
  |                                    |                                    |
  |  useCoAgent receives STATE_DELTA   |              ... nodes 1-6 ...    |
  |  useCopilotAction receives         |                                    |
  |    update_progress_status          |              Node 7: build_segment |
  |  ProgressStatus stepper updates    |                 |                  |
  |  ReasoningPanel shows COT          |              Claude LLM call       |
  |  ActivityIndicator shows progress  |              → Structured output   |
  |                                    |                 |                  |
  |                                    |              Final events:         |
  |                                    |              - STATE_SNAPSHOT      |
  |                                    |              - TEXT_MESSAGE_*      |
  |                                    |              - RUN_FINISHED        |
  |                                    |                 |                  |
  |                                    |              complete_run():       |
  |                                    |              → SET run_status = "completed"
  |                                    |              → DEL active_run:{tid}
  |                                    |              → PUBLISH STREAM_END  |
  |                                    |                                    |
  |  SegmentCard renders               |<── SSE: final events ─────────────|
  |  ProgressStatus shows "Complete"   |                                    |
  |  Assistant message appears         |                                    |
```

### 7.2 Reconnection (Connect Flow)

User reloads the page during pipeline execution:

```
Browser                          CopilotKit Runtime                    FastAPI Backend
──────                           ──────────────────                    ──────────────
  |                                    |                                    |
  |── Page reload ──────────────>     |                                    |
  |                                    |                                    |
  |  useAgentThread reads ?thread=...  |                                    |
  |  CopilotKit mounts with threadId   |                                    |
  |                                    |── JSON-RPC: agent/connect ────────>|
  |                                    |   { method: "agent/connect",       |
  |                                    |     body: { threadId } }           |
  |                                    |                                    |
  |  CopilotRuntime intercepts:        |                                    |
  |  (body.method === "agent/connect") |                                    |
  |                                    |── POST /api/v1/segment ──────────>|
  |                                    |   { thread_id, run_id,            |
  |                                    |     metadata: {requestType:"connect"}}
  |                                    |                                    |
  |                                    |                           _handle_connect():
  |                                    |                           1. Check active_run:{tid}
  |                                    |                              → active_run_id found!
  |                                    |                           2. catch_up_and_follow():
  |                                    |                              a. SUBSCRIBE agent:{tid}:{rid}
  |                                    |                              b. LRANGE events:{tid}:{rid} 0 -1
  |                                    |                                 → 15 events (nodes 0-1 done)
  |                                    |                              c. Yield 15 catch-up events
  |                                    |                              d. Yield MESSAGES_SNAPSHOT
  |                                    |                              e. Follow Pub/Sub (dedup seq>15)
  |                                    |                                    |
  |<── SSE: 15 events (fast-forward) ──|                                    |
  |                                    |                                    |
  |  Events replay rapidly:            |                                    |
  |  - ProgressStatus jumps to node 1  |                                    |
  |  - Reasoning panels flash by       |                                    |
  |  - State deltas applied            |                                    |
  |                                    |                                    |
  |<── SSE: live events (nodes 2+) ────|<── Pub/Sub: new events ───────────|
  |                                    |                                    |
  |  UI resumes normal streaming       |                                    |
  |  Pipeline completes normally       |                                    |
```

### 7.3 Duplicate Query Prevention

After pipeline completes, CopilotKit re-sends messages:

```
Browser                          CopilotKit Runtime                    FastAPI Backend
──────                           ──────────────────                    ──────────────
  |                                    |                                    |
  |  (Pipeline just finished)          |                                    |
  |  CopilotKit sends messages array   |                                    |
  |  with the same user query          |                                    |
  |                                    |── POST /api/v1/segment ──────────>|
  |                                    |   { messages: [...same query...], |
  |                                    |     metadata: {requestType:"chat"}}|
  |                                    |                                    |
  |                                    |                           _handle_chat():
  |                                    |                           1. Extract query from messages
  |                                    |                           2. Read checkpointer state
  |                                    |                           3. Compare last human message:
  |                                    |                              checkpointer: "Users from US..."
  |                                    |                              incoming:     "Users from US..."
  |                                    |                              → MATCH! Duplicate detected.
  |                                    |                           4. Return minimal response:
  |                                    |                                    |
  |                                    |<── SSE: RUN_STARTED ──────────────|
  |                                    |<── SSE: STATE_SNAPSHOT (segment) ──|
  |                                    |<── SSE: RUN_FINISHED ─────────────|
  |                                    |                                    |
  |  CopilotKit is satisfied           |                                    |
  |  (no new pipeline run started)     |                                    |
  |  Segment card preserved in UI      |                                    |
  |  No infinite loop                  |                                    |
```

The `STATE_SNAPSHOT` event in the duplicate response is critical. Without it, the `RUN_STARTED` event would reset CopilotKit's co-agent state to `{}`, causing the segment card to disappear. By replaying the segment data as a `STATE_SNAPSHOT`, the co-agent state is immediately restored.
