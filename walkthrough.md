# AG-UI Stream Reconnection Demo -- Comprehensive Walkthrough

## Table of Contents

- [1. Project Overview](#1-project-overview)
- [2. Architecture & Data Flow](#2-architecture--data-flow)
  - [2.1 System Architecture](#21-system-architecture)
  - [2.2 Strategy 1: Full Event Replay (Pub/Sub + List)](#22-strategy-1-full-event-replay-pubsub--list)
  - [2.3 Strategy 2: Checkpointer-Only Catch-Up](#23-strategy-2-checkpointer-only-catch-up)
  - [2.4 Strategy 3: ag-ui-langgraph + Checkpointer](#24-strategy-3-ag-ui-langgraph--checkpointer)
  - [2.5 CopilotKit Integration Flow](#25-copilotkit-integration-flow)
  - [2.6 Duplicate-Query Prevention](#26-duplicate-query-prevention)
- [3. Root Configuration Files](#3-root-configuration-files)
  - [3.1 pyproject.toml](#31-pyprojecttoml)
  - [3.2 justfile](#32-justfile)
  - [3.3 .gitignore](#33-gitignore)
- [4. Backend (Python)](#4-backend-python)
  - [4.1 Entry Point: main.py](#41-entry-point-mainpy)
  - [4.2 Schemas](#42-schemas)
    - [4.2.1 schemas/segment.py](#421-schemassegmentpy)
    - [4.2.2 schemas/template.py](#422-schemastemplatepy)
  - [4.3 Core Infrastructure](#43-core-infrastructure)
    - [4.3.1 core/events.py](#431-coreeventspy)
    - [4.3.2 core/pubsub.py](#432-corepubsubpy)
    - [4.3.3 core/agent_runner.py](#433-coreagent_runnerpy)
    - [4.3.4 core/middleware.py](#434-coremiddlewarepy)
    - [4.3.5 core/event_adapter.py](#435-coreevent_adapterpy)
  - [4.4 Agent: Segment Pipeline](#44-agent-segment-pipeline)
    - [4.4.1 agent/segment/state.py](#441-agentsegmentstatepy)
    - [4.4.2 agent/segment/graph.py](#442-agentsegmentgraphpy)
    - [4.4.3 agent/segment/routes.py](#443-agentsegmentroutespy)
  - [4.5 Agent: Stateful Segment Pipeline](#45-agent-stateful-segment-pipeline)
    - [4.5.1 agent/stateful_segment/routes.py](#451-agentstateful_segmentroutespy)
  - [4.6 Agent: Template Builder](#46-agent-template-builder)
    - [4.6.1 agent/template/state.py](#461-agenttemplatestatepy)
    - [4.6.2 agent/template/graph.py](#462-agenttemplatepy)
    - [4.6.3 agent/template/routes.py](#463-agenttemplateroutespy)
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
    - [6.2.5 app/template/page.tsx](#625-apptemplatepage.tsx)
  - [6.3 API Routes (CopilotRuntime Proxy)](#63-api-routes-copilotruntime-proxy)
    - [6.3.1 api/copilotkit/segment/route.ts](#631-apicopilotkitsegmentroutets)
    - [6.3.2 api/copilotkit/stateful-segment/route.ts](#632-apicopilotkitstateful-segmentroutets)
    - [6.3.3 api/copilotkit/template/route.ts](#633-apicopilotkittemplateroutets)
  - [6.4 Shared Components, Hooks, Types](#64-shared-components-hooks-types)
  - [6.5 Template Components](#65-template-components)
    - [6.5.1 components/TemplateEditor.tsx](#651-componentstemplateEditortsx)
    - [6.5.2 components/TemplatePreview.tsx](#652-componentstemplatepreviewtsx)
- [7. End-to-End Request Lifecycle](#7-end-to-end-request-lifecycle)
  - [7.1 New Query (Chat Flow)](#71-new-query-chat-flow)
  - [7.2 Reconnection (Connect Flow)](#72-reconnection-connect-flow)
  - [7.3 Duplicate Query Prevention](#73-duplicate-query-prevention)
  - [7.4 Template Agent Lifecycle](#74-template-agent-lifecycle)
- [8. Segment vs Template Agent: Feature Comparison](#8-segment-vs-template-agent-feature-comparison)
  - [8.1 Summary Table](#81-summary-table)
  - [8.2 What the Template Agent Is Missing](#82-what-the-template-agent-is-missing)
    - [8.2.1 Multi-Step Progress Tracking](#821-multi-step-progress-tracking)
    - [8.2.2 Reasoning Panels (Simulated)](#822-reasoning-panels-simulated)
    - [8.2.3 Incremental State Deltas](#823-incremental-state-deltas)
    - [8.2.4 Redis List Persistence for Full Event Replay](#824-redis-list-persistence-for-full-event-replay)
  - [8.3 Workarounds Required with ag-ui-langgraph](#83-workarounds-required-with-ag-ui-langgraph)
    - [8.3.1 EventAdapter (112 lines)](#831-eventadapter-112-lines)
    - [8.3.2 Pub/Sub-Only Agent Runner](#832-pubsub-only-agent-runner)
    - [8.3.3 State Injection via RunAgentInput](#833-state-injection-via-runagentinput)
    - [8.3.4 Custom Event Translation Pattern](#834-custom-event-translation-pattern)
    - [8.3.5 Missing clone() Call (Concurrency Bug)](#835-missing-clone-call-concurrency-bug)
  - [8.4 What the Library Provides for Free](#84-what-the-library-provides-for-free)
    - [8.4.1 Automatic Text Message Streaming](#841-automatic-text-message-streaming)
    - [8.4.2 Automatic MESSAGES_SNAPSHOT](#842-automatic-messages_snapshot)
    - [8.4.3 Automatic Run Lifecycle](#843-automatic-run-lifecycle)
    - [8.4.4 State Snapshot Suppression Logic](#844-state-snapshot-suppression-logic)
    - [8.4.5 Real LLM Reasoning Support](#845-real-llm-reasoning-support)
    - [8.4.6 Message Format Conversion](#846-message-format-conversion)
    - [8.4.7 Time-Travel and Interrupt/Resume](#847-time-travel-and-interruptresume)
  - [8.5 Code Volume Comparison](#85-code-volume-comparison)
  - [8.6 Frontend Impact](#86-frontend-impact)
  - [8.7 Verdict: When Each Approach Wins](#87-verdict-when-each-approach-wins)

---

## 1. Project Overview

This project is a proof-of-concept demonstrating **SSE stream reconnection** for AI agent pipelines. The core problem: in AG-UI applications, when a user reloads the browser during an active agent stream, the SSE connection drops but the backend continues processing. Events emitted after disconnect are lost, leaving the frontend in an inconsistent state.

The demo implements **two agents** (Segment Builder and Template Builder) with **three reconnection strategies**:

| Strategy | Agent | Endpoint | Event Generation | Catch-Up Source |
|----------|-------|----------|-----------------|-----------------|
| **Pub/Sub + List** | Segment | `POST /api/v1/segment` | Manual (`EventEmitter`) | Redis List (LRANGE) |
| **Checkpointer-Only** | Segment | `POST /api/v1/stateful-segment` | Manual (`EventEmitter`) | LangGraph MemorySaver |
| **ag-ui-langgraph** | Template | `POST /api/v1/template` | Auto (`LangGraphAgent` + `EventAdapter`) | LangGraph MemorySaver |

The segment agent manually emits every AG-UI event (~170 lines in `run_segment_pipeline()`). The template agent uses the `ag-ui-langgraph` library, which wraps `graph.astream_events()` and auto-translates LangGraph internals into AG-UI events. The `EventAdapter` bridges the library into the existing Redis pipeline.

**Tech stack:**

| Layer | Technology |
|-------|-----------|
| LLM | Claude Sonnet via `langchain-anthropic` |
| Agent framework | LangGraph with MemorySaver checkpointer |
| AG-UI automation | `ag-ui-langgraph` (template agent) |
| Backend | FastAPI + Uvicorn |
| Streaming protocol | AG-UI (SSE-based) |
| Event persistence | Redis Pub/Sub + Lists |
| Frontend (primary) | React 19 + Webpack (segment only) |
| Frontend (full) | Next.js 15 (both agents) |
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

### 2.4 Strategy 3: ag-ui-langgraph + Checkpointer

The template agent uses the `ag-ui-langgraph` library for automatic AG-UI event generation. Instead of manually emitting each event via `EventEmitter`, the library wraps `graph.astream_events()` and translates LangGraph internals into AG-UI events automatically.

```
                    New Run (Chat)
CopilotKit ─POST─> /api/v1/template ──> Start Background Task
  ^                     |                       |
  |                     |                LangGraphAgent.run()
  |                     |                  → EventAdapter (translates custom events, filters snapshots)
  |                     |                  → SSE strings
  |                     |                       |
  |                     v                       v
  <──── SSE ──── Pub/Sub Subscribe <── Pub/Sub Publish (only)

                    Reconnection (Connect)
CopilotKit ─POST─> /api/v1/template
  ^                     |
  |                1. Subscribe Pub/Sub (buffer live events)
  |                2. Read checkpointer state (MemorySaver)
  |                3. Yield synthetic catch-up events (MESSAGES_SNAPSHOT + STATE_SNAPSHOT)
  |                4. Yield live events (from Pub/Sub)
  <──── SSE ────────────┘
```

The key difference from Strategy 2: **event generation is automated**. The library handles RUN_STARTED/FINISHED, STEP_STARTED/FINISHED, STATE_SNAPSHOT, TEXT_MESSAGE_*, and REASONING_* events. Graph nodes only need to dispatch custom events (via `adispatch_custom_event`) for progress indicators, which the `EventAdapter` translates into proper AG-UI types.

Catch-up on reconnect uses the same checkpointer pattern as Strategy 2 (no Redis List). The LangGraph checkpointer is the single source of truth.

### 2.5 CopilotKit Integration Flow

CopilotKit uses two request types communicated via `metadata.requestType`:

| Scenario | requestType | Backend Action |
|----------|-------------|----------------|
| User sends new query | `chat` | Start background agent task, stream via Pub/Sub |
| CopilotKit re-sends same query | `chat` | Duplicate detected, return state snapshot |
| Browser reload / new tab | `connect` | Catch-up + bridge to live |
| Completed run reload | `connect` | Replay segment state from checkpointer |

CopilotKit's JSON-RPC protocol wraps requests as `agent/chat` or `agent/connect` methods. The CopilotRuntime proxy translates these into standard HTTP POST requests with the appropriate `requestType` in the metadata.

### 2.6 Duplicate-Query Prevention

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
    "ag-ui-langgraph>=0.0.29",
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
- **ag-ui-langgraph**: Wraps LangGraph's `astream_events()` to auto-generate AG-UI events. Used by the template agent via `LangGraphAgent`.
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
from ag_ui_langgraph import LangGraphAgent

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build segment agent graph with MemorySaver checkpointer
    checkpointer = MemorySaver()
    app.state.segment_graph = build_segment_graph(checkpointer=checkpointer)

    # Build a separate graph for stateful-segment (own checkpointer namespace)
    stateful_checkpointer = MemorySaver()
    app.state.stateful_segment_graph = build_segment_graph(checkpointer=stateful_checkpointer)

    # Build template agent graph with its own checkpointer
    template_checkpointer = MemorySaver()
    template_graph = build_template_graph(checkpointer=template_checkpointer)
    app.state.template_graph = template_graph
    app.state.template_agent = LangGraphAgent(name="template", graph=template_graph)

    # Initialize Redis Pub/Sub manager
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    app.state.pubsub = RedisPubSubManager(redis_url)

    yield

    await app.state.pubsub.close()
```

**Key design decisions:**

- **Three separate LangGraph graphs** with independent `MemorySaver` checkpointers. Each stores its own thread history independently.
- **`LangGraphAgent` wrapper** for the template agent. The `name="template"` parameter identifies the agent in AG-UI events. Both the raw graph (for checkpointer reads in `_handle_connect`) and the `LangGraphAgent` wrapper are stored on `app.state`.
- **Shared resources on `app.state`**: All graphs, agents, and the `pubsub` manager are attached to `app.state` so route handlers can access them via `request.app.state`.
- **CORS configured wide open** (`allow_origins=["*"]`) for development.

The app exposes four logical endpoints:
- `POST /api/v1/segment` -- Strategy 1: Pub/Sub + List (manual event emission)
- `POST /api/v1/stateful-segment` -- Strategy 2: Checkpointer-only (manual event emission)
- `POST /api/v1/template` -- ag-ui-langgraph + Checkpointer (auto event generation)
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

#### 4.2.2 schemas/template.py

**Path:** `src/stream_reconnection_demo/schemas/template.py`

Two Pydantic models define the structured output of the template agent:

```python
class TemplateSection(BaseModel):
    id: str                          # "s1", "s2", etc.
    type: str                        # header | body | footer | cta | image
    content: str                     # HTML content
    styles: dict[str, str] = {}      # Optional inline styles

class EmailTemplate(BaseModel):
    html: str = ""                   # Full HTML email
    css: str = ""                    # Global CSS
    subject: str = ""                # Email subject line
    preview_text: str = ""           # Email preview text
    sections: list[TemplateSection] = []
    version: int = 1                 # Version counter for tracking modifications
```

The `EmailTemplate` model is used by `ChatAnthropic.with_structured_output(EmailTemplate)` in both the `generate_template` and `modify_template` graph nodes. The `version` field increments on each modification.

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

#### 4.3.5 core/event_adapter.py

**Path:** `src/stream_reconnection_demo/core/event_adapter.py`

Bridges `LangGraphAgent.run()` output to SSE strings. This is the key integration layer between the `ag-ui-langgraph` library and the existing Redis pipeline.

```python
class EventAdapter:
    def __init__(self) -> None:
        self._encoder = EventEncoder()

    async def stream_events(self, agent, input_data, *, state_snapshot_key="template") -> AsyncIterator[str]:
        async for event_obj in agent.run(input_data):
            # Translate CUSTOM events to proper AG-UI types
            if event_obj.type == EventType.CUSTOM:
                async for translated in self._translate_custom(event_obj):
                    yield self._encoder.encode(translated)
                continue

            # Suppress intermediate STATE_SNAPSHOT where key is None
            if event_obj.type == EventType.STATE_SNAPSHOT:
                snapshot = getattr(event_obj, "snapshot", None) or {}
                if isinstance(snapshot, dict) and snapshot.get(state_snapshot_key) is None:
                    continue

            # Inject empty state reset after RUN_STARTED
            if event_obj.type == EventType.RUN_STARTED:
                yield self._encoder.encode(event_obj)
                yield self._encoder.encode(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot={}))
                continue

            yield self._encoder.encode(event_obj)
```

**Key responsibilities:**

1. **Custom event translation**: Intercepts `EventType.CUSTOM` events dispatched from graph nodes and translates them:
   - `"activity_snapshot"` → `ActivitySnapshotEvent` (progress indicator)
   - `"state_delta"` → `StateDeltaEvent` (incremental state updates)
   - Unknown custom events are silently dropped

2. **STATE_SNAPSHOT filtering**: The graph output schema (`TemplateOutput`) limits snapshots to `{template: ...}`. The adapter adds fine-tuning: suppresses intermediate `{template: null}` snapshots (emitted during node transitions before the LLM produces output), passes through the final snapshot with actual template data.

3. **State clearing after RUN_STARTED**: Injects an empty `StateSnapshotEvent({})` immediately after `RUN_STARTED`. This clears the frontend's co-agent state (segment card or template) so the previous result doesn't flash while the new run executes.

**Interface**: `stream_events()` → `AsyncIterator[str]` (SSE strings) — the **same interface** as `run_segment_pipeline()` and `run_stateful_segment_pipeline()`, so `agent_runner` needs zero changes. The `state_snapshot_key` parameter makes the adapter reusable for other agents (e.g., `state_snapshot_key="segment"` for a future segment agent migration).

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

### 4.6 Agent: Template Builder

The template agent uses the `ag-ui-langgraph` library for automatic AG-UI event generation, replacing the manual event emission pattern used by the segment agents.

#### 4.6.1 agent/template/state.py

**Path:** `src/stream_reconnection_demo/agent/template/state.py`

```python
class TemplateAgentState(TypedDict):
    messages: Annotated[list, add]   # LangChain messages (accumulated via reducer)
    template: dict | None            # Current template dict (None = first generation)
    error: str | None                # Error message if generation failed
    version: int                     # Template version counter

class TemplateOutput(TypedDict):
    """Output schema — limits STATE_SNAPSHOT to template field only."""
    template: dict | None
```

`TemplateOutput` is the graph's output schema. When LangGraph computes `get_state()`, only the `template` field is included. This ensures the library's auto-generated `STATE_SNAPSHOT` events contain `{template: ...}` rather than the full internal state (messages, error, version).

#### 4.6.2 agent/template/graph.py

**Path:** `src/stream_reconnection_demo/agent/template/graph.py`

Two-node graph with conditional routing:

```
START -> _route_by_state() -> generate_template -> END
                            -> modify_template  -> END
```

**Routing:**

```python
def _route_by_state(state: TemplateAgentState) -> str:
    if state.get("template") is None:
        return "generate_template"
    return "modify_template"
```

If no template exists in state, route to generation. Otherwise, route to modification. The `state` dict includes `template` from the `RunAgentInput.state` passed by the routes — which reads from either the frontend state or the checkpointer.

**Nodes:**

Both nodes follow the same pattern: extract query from messages, dispatch activity custom events for progress, invoke Claude with structured output, return the result:

```python
def _build_generate_node(llm: ChatAnthropic):
    structured_llm = llm.with_structured_output(EmailTemplate)

    async def generate_template(state: TemplateAgentState, config: RunnableConfig) -> dict:
        query = ""
        for msg in reversed(state["messages"]):
            if hasattr(msg, "content"):
                query = msg.content
                break

        await adispatch_custom_event("activity_snapshot", {
            "title": "Generating template", "progress": 0.1,
            "details": "Starting LLM generation...",
        }, config=config)

        messages = [SystemMessage(content=GENERATE_SYSTEM_PROMPT), HumanMessage(content=query)]
        result = await structured_llm.ainvoke(messages, config=config)

        await adispatch_custom_event("activity_snapshot", {
            "title": "Template generated", "progress": 1.0,
            "details": f"Created: {result.subject}",
        }, config=config)

        return {"template": result.model_dump(), "error": None, "version": 1}

    return generate_template
```

The `modify_template` node is similar but includes the existing template context in the system prompt (subject, sections summary, full HTML) and increments the version counter.

**System prompts:**
- `GENERATE_SYSTEM_PROMPT`: Instructs Claude to create a professional HTML email template with inline CSS, 600px container, sections (header/body/CTA/footer), and web-safe fonts.
- `MODIFY_SYSTEM_PROMPT`: Includes the current template context and instructs Claude to apply the user's requested changes while preserving unmentioned sections.

**Custom events:** Each node dispatches `adispatch_custom_event("activity_snapshot", ...)` at 10% and 100% progress. The `EventAdapter` translates these into `ActivitySnapshotEvent` objects. Note: the `config: RunnableConfig` parameter is required for `adispatch_custom_event` — LangGraph auto-injects it when the function signature accepts it.

**Graph compilation:**

```python
def build_template_graph(checkpointer=None, model="claude-sonnet-4-20250514"):
    llm = ChatAnthropic(model=model)
    graph = StateGraph(TemplateAgentState, output=TemplateOutput)
    graph.add_node("generate_template", _build_generate_node(llm))
    graph.add_node("modify_template", _build_modify_node(llm))
    graph.add_conditional_edges(START, _route_by_state)
    graph.add_edge("generate_template", END)
    graph.add_edge("modify_template", END)
    return graph.compile(checkpointer=checkpointer)
```

The `output=TemplateOutput` parameter limits the graph's output schema, which controls what the library includes in `STATE_SNAPSHOT` events.

#### 4.6.3 agent/template/routes.py

**Path:** `src/stream_reconnection_demo/agent/template/routes.py`

Defines `POST /api/v1/template` and `GET /api/v1/template/state/{thread_id}`. Uses the same request/response patterns as the segment routes but with `EventAdapter` + `LangGraphAgent` instead of manual event emission.

**`handle_template()`: Request dispatcher**

```python
@router.post("/template")
async def handle_template(request: Request):
    body = await request.json()
    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    query = extract_user_query(body.get("messages", []))
    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    if request_type == "connect":
        return await _handle_connect(pubsub, template_graph, thread_id, run_id)
    return await _handle_chat(pubsub, template_graph, template_agent, thread_id, run_id, query, frontend_state)
```

**`_handle_chat()`: New run via LangGraphAgent + EventAdapter**

1. Duplicate query detection via checkpointer (same pattern as segment).
2. If duplicate: return minimal run (`RUN_STARTED` + `STATE_SNAPSHOT` with template + `RUN_FINISHED`).
3. Build `RunAgentInput` with the user message and existing template state (from frontend or checkpointer).
4. Create `EventAdapter().stream_events(template_agent, input_data)` — yields SSE strings.
5. Pass to `start_agent_task_pubsub_only()` — publishes each SSE string to Redis Pub/Sub.
6. Return `StreamingResponse` with `pubsub.subscribe_and_stream()`.

```python
input_data = RunAgentInput(
    thread_id=thread_id, run_id=run_id,
    messages=[UserMessage(id=str(uuid.uuid4()), role="user", content=query)],
    state={"template": existing_template, "version": ...},
    tools=[], context=[], forwarded_props={},
)

adapter = EventAdapter()
event_stream = adapter.stream_events(template_agent, input_data, state_snapshot_key="template")
start_agent_task_pubsub_only(pubsub, template_graph, thread_id, run_id, event_stream)
```

The `RunAgentInput.state` field passes the existing template to the graph, which enables the `_route_by_state()` conditional to correctly choose between generate and modify.

**`_handle_connect()`: Catch-up from checkpointer**

Same pattern as `_handle_stateful_connect` in the stateful segment routes:

1. **Active run found**: Subscribe to Pub/Sub first (buffer), read checkpointer state, emit synthetic catch-up events (`RUN_STARTED` + `MESSAGES_SNAPSHOT` + `STATE_SNAPSHOT`), yield live Pub/Sub events. On stream end, read final state from checkpointer for the template result.
2. **Completed run (no active)**: Emit synthetic catch-up from checkpointer + `RUN_FINISHED`.
3. **Nothing found**: Empty run (`RUN_STARTED` + `RUN_FINISHED`).

**`_emit_synthetic_catchup()`: Reconstruct events from checkpointer state**

```python
async def _emit_synthetic_catchup(state, thread_id, run_id):
    yield emitter.emit_run_started(thread_id, run_id)
    messages = state.get("messages", [])
    if messages:
        agui_msgs = emitter.langchain_messages_to_agui(messages)
        if agui_msgs:
            yield emitter.emit_messages_snapshot(agui_msgs)
    template = state.get("template")
    if template:
        yield emitter.emit_state_snapshot(template)
```

Simpler than the segment's `_emit_synthetic_catchup` — no progress stepper reconstruction needed since the template agent is a single-step LLM call.

**State endpoint:**

```python
@router.get("/template/state/{thread_id}")
async def get_template_state(thread_id: str, request: Request):
    """Return current template state from checkpointer for a given thread."""
```

Direct checkpointer read returning `{template: ...}` or `{template: null}`.

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

Simple navigation header with the app title and a "Segment Builder" label. The React+Webpack frontend only supports the segment agent:

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

Note: The Next.js `Nav.tsx` has been updated to include both "Segment Builder" and "Template Builder" tabs with active state based on `usePathname()` (see section 6.4).

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

Also defines `ThreadSummary`, `ThreadMessage`, and `ThreadData` interfaces for thread management. The Next.js version additionally includes `TemplateSection` and `EmailTemplate` interfaces for the template agent (see section 6.4).

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

A card grid home page with links to both agents:

```tsx
const agents = [
  { href: "/segment", title: "Segment Builder", description: "Build audience segments with an 8-step AI pipeline..." },
  { href: "/template", title: "Template Builder", description: "Create and modify email templates with AI..." },
];

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
      <div className="max-w-3xl w-full px-6 py-16">
        <h1 className="text-2xl font-bold text-center mb-2">Stream Reconnection Demo</h1>
        <p className="text-sm text-gray-500 text-center mb-10">Choose an agent to get started</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {agents.map((agent) => (
            <Link key={agent.href} href={agent.href} className="block p-6 rounded-xl border ...">
              <h2>{agent.title}</h2>
              <p>{agent.description}</p>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
```

Replaces the previous `redirect("/segment")` with a two-card layout. Each card links to the respective agent page.

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

#### 6.2.5 app/template/page.tsx

**Path:** `frontend-next/app/template/page.tsx`

The template builder page. Structure:

```
TemplatePage (Suspense wrapper)
  -> TemplatePageInner (useAgentThread)
      -> CopilotKit (runtimeUrl="/api/copilotkit/template", threadId)
          -> CopilotSidebar (defaultOpen=true, RenderMessage=CustomRenderMessage)
              -> TemplatePageContent
                  - useCoAgent<EmailTemplate>({ name: "default" }) -> template state
                  - useCoAgentStateRender -> inline "Template updated" notification
                  - Content: Nav + TemplateEditor (when template.subject exists) or placeholder
```

```tsx
function TemplatePageContent() {
  useCoAgentStateRender({
    name: "default",
    render: ({ state }) =>
      state?.subject ? (
        <div className="... bg-green-50 ...">Template updated: {state.subject}</div>
      ) : null,
  });

  const { state: template, setState: setTemplate } = useCoAgent<EmailTemplate>({ name: "default" });

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 overflow-hidden">
        {template?.subject ? (
          <TemplateEditor template={template} onHtmlChange={(html) => setTemplate({ ...template, html })} />
        ) : (
          <div className="flex items-center justify-center h-full">
            <p>Describe your email template in the sidebar to get started.</p>
          </div>
        )}
      </main>
    </div>
  );
}
```

Key differences from segment page:
- Uses `useCoAgent<EmailTemplate>` instead of `useCoAgent<Segment>`
- No `useCopilotAction("update_progress_status")` — the template agent doesn't emit progress tool calls
- `useCoAgentStateRender` renders an inline notification when the template is updated (vs. `render: () => null` in segment)
- Content area shows `TemplateEditor` with live HTML preview instead of `SegmentCard` with conditions

**CustomRenderMessage:** Same pattern as segment page — filters old reasoning/activity messages, renders user/assistant messages. Slightly simpler since there's no `InlineSegmentCard`.

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

#### 6.3.3 api/copilotkit/template/route.ts

**Path:** `frontend-next/app/api/copilotkit/template/route.ts`

Same pattern as the segment route — `CopilotRuntime` with `LangGraphHttpAgent` pointing to the backend, with `agent/connect` interception for reconnection:

```typescript
const runtime = new CopilotRuntime({
  agents: {
    default: new LangGraphHttpAgent({
      url: `${BACKEND_URL}/api/v1/template`,
      description: "Email template creator",
    }),
  },
});

export const POST = async (req: Request) => {
  const body = await req.json();

  if (body.method === "agent/connect") {
    // Proxy directly to backend with requestType: "connect"
    const backendResp = await fetch(`${BACKEND_URL}/api/v1/template`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: threadId, run_id: runId,
        messages: body.body?.messages ?? [],
        metadata: { requestType: "connect" },
      }),
    });
    return new Response(backendResp.body, { status: backendResp.status, headers: { "Content-Type": "text/event-stream" } });
  }

  // Non-connect: pass to CopilotKit handler
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({ runtime, serviceAdapter: new EmptyAdapter(), endpoint: "/api/copilotkit/template" });
  return handleRequest(newReq);
};
```

### 6.4 Shared Components, Hooks, Types

The `frontend-next/components/`, `frontend-next/hooks/`, and `frontend-next/lib/` directories contain the same segment components as the React+Webpack frontend with minor differences:

| Difference | React+Webpack | Next.js |
|-----------|--------------|---------|
| `Nav.tsx` | Uses `<a href="/">`, single tab | Uses `<Link href="/">` from `next/link`, two tabs with active state via `usePathname()` |
| Components | No directive needed | Add `"use client"` to `ProgressStatus.tsx`, `ReasoningPanel.tsx` |
| `useAgentThread.ts` | Direct `window.location` access | Guards with `typeof window === "undefined"` for SSR |
| CSS imports | `@import "@copilotkit/react-ui/styles.css"` in CSS | `import` in `layout.tsx` |

The Next.js `Nav.tsx` now includes tab navigation between both agents:

```tsx
export function Nav() {
  const pathname = usePathname();
  const tabs = [
    { href: "/segment", label: "Segment Builder" },
    { href: "/template", label: "Template Builder" },
  ];
  return (
    <header className="border-b ...">
      <Link href="/">Stream Reconnection Demo</Link>
      <nav className="flex gap-1 bg-gray-100 rounded-lg p-1">
        {tabs.map((tab) => (
          <Link key={tab.href} href={tab.href}
            className={pathname === tab.href ? "bg-white shadow-sm" : "text-gray-500"}>
            {tab.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
```

The `lib/types.ts` file now includes both segment and template types:

```typescript
// Segment types (unchanged)
export interface Condition { field: string; operator: string; value: string | number | string[]; }
export interface ConditionGroup { logical_operator: "AND" | "OR"; conditions: Condition[]; }
export interface Segment { name: string; description: string; condition_groups: ConditionGroup[]; estimated_scope?: string; }

// Template types (new)
export interface TemplateSection { id: string; type: string; content: string; styles?: Record<string, string>; }
export interface EmailTemplate { html: string; css: string; subject: string; preview_text: string; sections: TemplateSection[]; version: number; }
```

### 6.5 Template Components

#### 6.5.1 components/TemplateEditor.tsx

**Path:** `frontend-next/components/TemplateEditor.tsx`

Renders the template metadata bar and preview wrapper:

```tsx
export function TemplateEditor({ template, onHtmlChange }: TemplateEditorProps) {
  return (
    <div className="flex flex-col h-full">
      {/* Metadata bar: subject, preview text, version */}
      <div className="flex items-center gap-4 px-4 py-2 border-b ...">
        <h3 className="text-sm font-semibold truncate">{template.subject || "Untitled"}</h3>
        {template.preview_text && <span className="text-xs text-gray-500 truncate">{template.preview_text}</span>}
        <span className="text-xs text-gray-400 ml-auto">v{template.version}</span>
      </div>

      {/* Editable preview */}
      <div className="flex-1 min-h-0">
        <TemplatePreview html={template.html} css={template.css} editable onHtmlChange={onHtmlChange} />
      </div>
    </div>
  );
}
```

The metadata bar shows the email subject, preview text (hidden on small screens), and version number. The `onHtmlChange` callback flows up to the `TemplatePageContent` component where `setTemplate` updates the co-agent state.

#### 6.5.2 components/TemplatePreview.tsx

**Path:** `frontend-next/components/TemplatePreview.tsx`

Renders the email template HTML in a sandboxed iframe with optional inline editing:

```tsx
export function TemplatePreview({ html, css, editable = false, onHtmlChange }: TemplatePreviewProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const userEditHtml = useRef<string | null>(null);

  useEffect(() => {
    const iframe = iframeRef.current;
    const doc = iframe?.contentDocument;
    if (!doc) return;

    // Skip rewrite when the html prop is just feedback from a user edit
    if (userEditHtml.current !== null && userEditHtml.current === html) return;
    userEditHtml.current = null;

    doc.open();
    doc.write(`<!DOCTYPE html><html><head><style>${css}</style></head><body>${html}</body></html>`);
    doc.close();

    if (editable) {
      doc.designMode = "on";
      doc.addEventListener("input", () => {
        const newHtml = doc.body.innerHTML;
        userEditHtml.current = newHtml;
        onHtmlChangeRef.current?.(newHtml);
      });
    }
  }, [html, css, editable]);

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 border-b ...">
        <span className="text-xs">Preview</span>
        {editable && <span className="text-xs text-blue-500">Click to edit</span>}
      </div>
      <iframe ref={iframeRef} className="flex-1 w-full bg-white" sandbox="allow-same-origin" title="Template Preview" />
    </div>
  );
}
```

Key details:
- The `sandbox="allow-same-origin"` attribute allows the parent page to access the iframe's DOM for `designMode` editing while preventing the iframe from running scripts.
- The `userEditHtml` ref prevents rewrite loops: when the user edits the HTML in the iframe, the `onHtmlChange` callback updates the parent state, which flows back as a new `html` prop. Without the guard, this would overwrite the user's cursor position and edits.
- `designMode = "on"` makes the entire iframe document contentEditable, allowing the user to click and edit the template text directly.

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

### 7.4 Template Agent Lifecycle

The template agent follows the same high-level flow but with automated event generation:

**New Template (Chat Flow):**

```
Browser                          CopilotKit Runtime                    FastAPI Backend
──────                           ──────────────────                    ──────────────
  |                                    |                                    |
  |── User types: "Welcome email      |                                    |
  |   for SaaS users" ──────────>    |                                    |
  |                                    |── POST /api/v1/template ─────────>|
  |                                    |   { messages, metadata:           |
  |                                    |     {requestType: "chat"} }       |
  |                                    |                                    |
  |                                    |                           _handle_chat():
  |                                    |                           1. Check duplicate → no match
  |                                    |                           2. pubsub.start_run()
  |                                    |                           3. Build RunAgentInput
  |                                    |                              (state.template = null → generate)
  |                                    |                           4. EventAdapter.stream_events()
  |                                    |                              → LangGraphAgent.run()
  |                                    |                           5. start_agent_task_pubsub_only()
  |                                    |                                    |
  |                                    |              Background task:      |
  |                                    |              LangGraphAgent.run()  |
  |                                    |                 |                  |
  |                                    |              _route_by_state()     |
  |                                    |              → generate_template   |
  |                                    |                 |                  |
  |                                    |              Library auto-emits:   |
  |                                    |              - RUN_STARTED         |
  |                                    |              - STEP_STARTED        |
  |                                    |                 |                  |
  |                                    |              EventAdapter:         |
  |                                    |              - Injects STATE_SNAPSHOT {} |
  |                                    |              - Translates activity |
  |                                    |                custom events      |
  |                                    |              - Filters null       |
  |                                    |                STATE_SNAPSHOT     |
  |                                    |                 |                  |
  |                                    |              Claude LLM call      |
  |                                    |              (structured output)  |
  |                                    |                 |                  |
  |                                    |              Library auto-emits:   |
  |                                    |              - TEXT_MESSAGE_*      |
  |                                    |              - STATE_SNAPSHOT      |
  |                                    |                {template: {...}}  |
  |                                    |              - STEP_FINISHED       |
  |                                    |              - RUN_FINISHED        |
  |                                    |                                    |
  |<── SSE: events via Pub/Sub ────────|<── Pub/Sub: events ───────────────|
  |                                    |                                    |
  |  useCoAgent receives               |                                    |
  |    STATE_SNAPSHOT with template    |                                    |
  |  TemplateEditor renders            |                                    |
  |  (subject, preview, HTML iframe)   |                                    |
```

**Modify Template (subsequent query):**

```
  |── User types: "Change the CTA     |                                    |
  |   button to blue" ───────────>    |                                    |
  |                                    |── POST /api/v1/template ─────────>|
  |                                    |                                    |
  |                                    |                           _handle_chat():
  |                                    |                           1. Check duplicate → no match
  |                                    |                           2. Build RunAgentInput
  |                                    |                              (state.template = existing → modify)
  |                                    |                                    |
  |                                    |              _route_by_state()     |
  |                                    |              → modify_template     |
  |                                    |                 |                  |
  |                                    |              System prompt includes|
  |                                    |              existing template     |
  |                                    |              context (subject,     |
  |                                    |              sections, HTML)       |
  |                                    |                 |                  |
  |                                    |              Claude modifies,      |
  |                                    |              version increments    |
  |                                    |                                    |
  |  TemplateEditor re-renders         |<── STATE_SNAPSHOT {version: 2} ───|
  |  with updated template             |                                    |
```

**Key differences from segment lifecycle:**
- **No 8-step stepper**: Template agent is a single-step LLM call, not a multi-node pipeline
- **No reasoning panels**: The library auto-generates reasoning events from the LLM stream, but the template page uses the same filtering as segment (only shows the latest during processing)
- **Conditional routing**: Generate vs. modify is determined by the presence of existing template state
- **EventAdapter**: Sits between `LangGraphAgent.run()` and the Redis pipeline, translating custom events and filtering intermediate snapshots

---

## 8. Segment vs Template Agent: Feature Comparison

This section compares the **segment agent** (manual AG-UI event emission, no `ag-ui-langgraph`) with the **template agent** (uses `ag-ui-langgraph` via `LangGraphAgent` + `EventAdapter`). It catalogs missing functionality, workarounds required, and additional capabilities gained by adopting the library.

### 8.1 Summary Table

| Capability | Segment (Manual) | Template (ag-ui-langgraph) | Notes |
|---|---|---|---|
| **Run lifecycle** (RUN_STARTED / RUN_FINISHED / RUN_ERROR) | Manual `emit_run_started()` etc. | Auto from `LangGraphAgent._handle_stream_events()` | Library handles all three automatically |
| **Text message streaming** | Manual `emit_text_start/content/end()` | Auto from `on_chat_model_stream` events | Library listens to `astream_events()` tokens |
| **State snapshots** | Manual `emit_state_snapshot(segment.model_dump())` | Auto final STATE_SNAPSHOT at stream end; EventAdapter filters intermediates | Library emits snapshot of full graph state; EventAdapter extracts domain key |
| **State deltas** (JSON Patch) | Manual `emit_state_delta(ops)` with `_DELTA_FIELDS` list | Not used (no incremental state updates emitted) | Library supports it via `ManuallyEmitState` custom event, but template agent doesn't use it |
| **Step tracking** | Manual `emit_step_start/finish()` per node | Not emitted | Library has no step concept; would need custom events |
| **Tool call progress** | Manual `emit_tool_call_start/args/end("update_progress_status")` | Not emitted | Segment uses fake tool calls to drive `useCopilotAction` on frontend |
| **Activity indicators** | Manual `emit_activity_snapshot()` | `adispatch_custom_event("activity_snapshot")` → EventAdapter translates to `ActivitySnapshotEvent` | Works, but requires EventAdapter translation layer |
| **Reasoning panels** | Manual `emit_reasoning_start/content/end()` with `asyncio.sleep(0.05)` delays | Auto from LLM if extended thinking enabled; no manual emission possible | Library auto-detects `on_chat_model_stream` reasoning tokens; no `ManuallyEmitReasoning` custom event exists |
| **Messages snapshot** | Manual `emit_messages_snapshot()` with `langchain_messages_to_agui()` | Auto MESSAGES_SNAPSHOT at stream end | Library handles conversion and emission |
| **Reconnection** | Redis List + Pub/Sub (full replay) | Checkpointer-only (synthetic catch-up via `_emit_synthetic_catchup()`) | Different strategies; both work |
| **Progress bar** (multi-step) | `useCopilotAction("update_progress_status")` with node/index/total | Not available | Template is single-step, but even if multi-step, no mechanism to drive it |
| **Inline state render** | `useCoAgentStateRender` → `SegmentCard` inline after assistant message | `useCoAgentStateRender` → green banner; `useCoAgent` → `TemplateEditor` | Both use the same CopilotKit hooks |
| **Duplicate query prevention** | Checkpointer message comparison | Checkpointer message comparison | Identical implementation |
| **Error handling** | `emit_run_error()` in routes | Auto RUN_FINISHED with error; `EventAdapter` passes through | Library handles error finalization |
| **Concurrent request safety** | Each request gets its own pipeline generator | **Bug**: `template_agent` on `app.state` shared without `clone()` | Library requires `agent.clone()` per request |

### 8.2 What the Template Agent Is Missing

#### 8.2.1 Multi-Step Progress Tracking

The segment agent provides granular progress via two mechanisms:

**1. Tool-call-based progress (`useCopilotAction`)**

The segment agent emits fake tool calls that the frontend intercepts:

```python
# segment/routes.py — emits a tool call the frontend handles as a progress update
yield emitter.emit_tool_call_start(
    tool_call_id=f"progress-{node_name}",
    tool_name="update_progress_status",
    parent_message_id=msg_id,
)
yield emitter.emit_tool_call_args(
    tool_call_id=f"progress-{node_name}",
    delta=json.dumps({
        "status": "processing",
        "node": node_name,
        "node_index": idx,
        "total_nodes": 8,
    }),
)
yield emitter.emit_tool_call_end(tool_call_id=f"progress-{node_name}")
```

The frontend catches this with `useCopilotAction("update_progress_status")` and renders a `<ProgressStatus>` component showing "Step 3/8 — Validating fields...".

The template agent has **no equivalent**. The library's `LangGraphAgent` does not emit step events or tool-call events for non-tool nodes. There is no mechanism to inject fake tool calls through the library — `CustomEventNames` only supports `ManuallyEmitMessage`, `ManuallyEmitToolCall`, `ManuallyEmitState`, and `Exit`.

**2. Step events**

```python
# segment/routes.py
yield emitter.emit_step_start(step_id)
# ... node processing ...
yield emitter.emit_step_finish(step_id)
```

The library has no concept of "steps." Step events (`STEP_STARTED`, `STEP_FINISHED`) are not emitted by `LangGraphAgent`.

#### 8.2.2 Reasoning Panels (Simulated)

The segment agent emits hand-crafted reasoning content from `NODE_META`:

```python
# segment/routes.py — simulated reasoning with streaming delays
yield emitter.emit_reasoning_start()
yield emitter.emit_reasoning_message_start(msg_id)
for line in meta["reasoning"]:          # pre-written reasoning steps
    yield emitter.emit_reasoning_content(line + "\n")
    await asyncio.sleep(0.05)           # typewriter effect
yield emitter.emit_reasoning_message_end()
yield emitter.emit_reasoning_end()
```

The `NODE_META` dictionary (lines 18-115 of `segment/routes.py`) defines step-by-step reasoning strings per node, e.g.:

```python
"analyze_requirements": {
    "reasoning": [
        "Breaking down user request into components...",
        "Identifying key audience attributes mentioned...",
        "Mapping natural language to available field types...",
    ],
    ...
}
```

The template agent **cannot emit fake reasoning**. The library auto-detects reasoning from LLM stream events (`on_chat_model_stream`) when extended thinking is enabled on the model. But:
- There is no `ManuallyEmitReasoning` in `CustomEventNames`
- `adispatch_custom_event` with a reasoning-related name would land as a `CUSTOM` event, not a `REASONING` event
- The EventAdapter only translates `"activity_snapshot"` and `"state_delta"` custom events

Real LLM reasoning would work (enable `extended_thinking` on `ChatAnthropic`), but the segment agent's handcrafted, deterministic reasoning UX is not replicable through the library.

#### 8.2.3 Incremental State Deltas

The segment agent emits JSON Patch operations as each node completes:

```python
# segment/routes.py
_DELTA_FIELDS = [
    "requirements", "entities", "validated_fields",
    "operator_mappings", "conditions_draft",
    "optimized_conditions", "scope_estimate",
]

# After each node, emit deltas for new fields
for field in _DELTA_FIELDS:
    if field in node_output:
        ops = [{"op": "replace", "path": f"/{field}", "value": node_output[field]}]
        yield emitter.emit_state_delta(ops)
```

The frontend receives these as `STATE_DELTA` events and incrementally updates `useCoAgent` state.

The template agent does **not emit state deltas**. It only emits a single `STATE_SNAPSHOT` at the end of the run (after `_assemble_html()` completes). The library supports `ManuallyEmitState` custom events, but the template agent's graph nodes don't use them. The result: the frontend sees nothing until the entire LLM call finishes — no partial template preview during generation.

#### 8.2.4 Redis List Persistence for Full Event Replay

The segment agent persists every SSE event to a Redis List:

```python
# pubsub.py
async def publish_event(self, thread_id, run_id, event_data):
    key = self.events_key(thread_id, run_id)
    seq = await self._redis.rpush(key, event_data)   # persist
    await self._redis.expire(key, self._ttl)
    await self._redis.publish(channel, envelope)       # fan-out
    return seq
```

On reconnection, it replays the full event stream from the List (`LRANGE 0 -1`), giving the frontend an identical experience to the original — including activity indicators, reasoning panels, progress steps, and partial deltas.

The template agent uses **Pub/Sub only** (`start_agent_task_pubsub_only`). Reconnection reconstructs state synthetically from the checkpointer:

```python
# template/routes.py — _emit_synthetic_catchup()
yield emitter.emit_run_started(run_id)
yield emitter.emit_messages_snapshot(messages, thread_id)
if template_data:
    yield emitter.emit_state_snapshot(template_data)
```

This means reconnection only restores the **final state**, not the journey. No activity indicators, no progress, no reasoning — just the end result. For the template agent this is acceptable (single LLM call, few seconds), but it would be inadequate for a multi-step pipeline.

### 8.3 Workarounds Required with ag-ui-langgraph

#### 8.3.1 EventAdapter (112 lines)

The library's `LangGraphAgent.run()` yields AG-UI event objects, but they don't match what the existing infrastructure expects:

| Problem | Workaround in EventAdapter |
|---|---|
| `STATE_SNAPSHOT` contains full graph state (messages, template, error, version) — frontend only needs `template` | Extract `snapshot.get("template")`, rebuild `StateSnapshotEvent` with just the domain object |
| Intermediate `STATE_SNAPSHOT` events fire when `template` is still `None` (graph entered node but LLM hasn't returned) | Skip snapshots where extracted value is `None` |
| Frontend `useCoAgent` expects an empty object on new run start to clear stale state | Inject `StateSnapshotEvent(snapshot={})` immediately after `RUN_STARTED` |
| `adispatch_custom_event("activity_snapshot", {...})` arrives as `EventType.CUSTOM` | Translate to `ActivitySnapshotEvent` with proper fields (message_id, activity_type, content) |
| `adispatch_custom_event("state_delta", {"ops": [...]})` arrives as `EventType.CUSTOM` | Translate to `StateDeltaEvent` with `delta=ops` |

Without the EventAdapter, the frontend would receive:
- Full graph state (with `messages` array, `error`, `version`) instead of just the template object
- Stale intermediate snapshots that would flash empty state in the UI
- Raw `CUSTOM` events that CopilotKit doesn't understand

#### 8.3.2 Pub/Sub-Only Agent Runner

The library produces event objects, not SSE strings. The existing `run_agent_background()` in `agent_runner.py` expects an `AsyncIterator[str]` of SSE lines. Two adaptations were needed:

1. `EventAdapter.stream_events()` wraps `agent.run()` and yields `str` (via `EventEncoder.encode()`)
2. `start_agent_task_pubsub_only()` was added to `agent_runner.py` for Pub/Sub-only publishing (no Redis List persistence)

```python
# agent_runner.py — Pub/Sub-only variant for library-based agents
async def run_agent_pubsub_only(pubsub, thread_id, run_id, event_stream):
    seq_counter = 0
    async for event_sse in event_stream:
        seq_counter += 1
        await pubsub._redis.publish(
            channel, json.dumps({"seq": seq_counter, "event": event_sse})
        )
    await pubsub.complete_run(thread_id, run_id)
```

#### 8.3.3 State Injection via RunAgentInput

The library's `LangGraphAgent` needs to know the existing template state so `_route_by_state()` can choose between generate and modify. This requires packaging the state into `RunAgentInput`:

```python
# template/routes.py — _handle_chat()
existing_template = None
if state_data:
    existing_template = state_data.get("template")

input_data = RunAgentInput(
    thread_id=thread_id,
    run_id=run_id,
    messages=agui_messages,
    state={"template": existing_template} if existing_template else None,
)
```

The segment agent doesn't need this — its checkpointer state automatically persists across invocations.

#### 8.3.4 Custom Event Translation Pattern

The graph nodes cannot emit proper AG-UI events directly. They use LangGraph's `adispatch_custom_event()` which becomes a `CUSTOM` event in the library's output. The EventAdapter then translates:

```python
# graph.py — inside generate/modify nodes
await adispatch_custom_event(
    "activity_snapshot",
    {"title": "Generating template", "progress": 0.1, "details": "Starting..."},
    config=config,
)

# event_adapter.py — translation
if name == "activity_snapshot":
    yield ActivitySnapshotEvent(
        type=EventType.ACTIVITY_SNAPSHOT,
        message_id=str(uuid.uuid4()),
        activity_type="processing",
        content=data,
    )
```

This is a two-hop indirection: graph node → `adispatch_custom_event` → LangGraph `astream_events` → `LangGraphAgent.run()` → EventAdapter → SSE string. In the segment agent, it's a single hop: `emitter.emit_activity_snapshot()` → SSE string.

#### 8.3.5 Missing clone() Call (Concurrency Bug)

The library documentation and test suite (`test_clone.py`) make clear that `LangGraphAgent` has mutable per-request state (`active_run`, message tracking). Each concurrent request needs `agent.clone()`:

```python
# endpoint.py (library) — correct pattern
agent_instance = agent.clone()  # fresh copy per request
async for event in agent_instance.run(input_data):
    ...
```

The template agent stores a single `template_agent` on `request.app.state` and passes it directly to `EventAdapter.stream_events()` without cloning. Two simultaneous requests would corrupt shared state. This is a bug, not an intentional workaround.

### 8.4 What the Library Provides for Free

#### 8.4.1 Automatic Text Message Streaming

The library hooks into `on_chat_model_stream` events from `astream_events(version="v2")` and automatically emits:

```
TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT (per token) → TEXT_MESSAGE_END
```

The segment agent would need ~15 lines of manual emission per text stream. The template agent gets this with zero code — the library detects the `ChatAnthropic` call inside the graph node and streams tokens.

However, for the template agent this is somewhat wasted: the LLM uses `with_structured_output(EmailTemplate)`, so the "text" streamed is actually JSON fragments of the structured output, not user-visible prose. The frontend doesn't display this text stream — it waits for the final `STATE_SNAPSHOT` with the assembled template.

#### 8.4.2 Automatic MESSAGES_SNAPSHOT

At the end of every run, the library emits a `MESSAGES_SNAPSHOT` containing the full conversation history converted from LangChain format to AG-UI format. This handles:

- `HumanMessage` → `{role: "user", content: "..."}`
- `AIMessage` → `{role: "assistant", content: "..."}`
- Multimodal content (images, tool results)
- Message deduplication

The segment agent does this manually:

```python
# segment/routes.py — _handle_connect()
agui_messages = emitter.langchain_messages_to_agui(lc_messages)
yield emitter.emit_messages_snapshot(agui_messages, thread_id)
```

#### 8.4.3 Automatic Run Lifecycle

`RUN_STARTED`, `RUN_FINISHED`, and `RUN_ERROR` are all emitted automatically by `_handle_stream_events()`. The segment agent manually emits each:

```python
yield emitter.emit_run_started(run_id)
# ... 170 lines of pipeline logic ...
yield emitter.emit_run_finished(run_id)
```

Error handling in the library is also automatic — if the graph throws, `RUN_FINISHED` is emitted with the error.

#### 8.4.4 State Snapshot Suppression Logic

The library has sophisticated logic to avoid emitting stale state snapshots when tool calls are in flight:

```python
# agent.py — suppression logic
suppressed = exiting_node and (model_made_tool_call or not state_reliable)
```

This prevents the frontend from flashing stale state between tool call and tool result. The segment agent doesn't need this (no tool calls), but if it were extended with tools, implementing equivalent suppression manually would be non-trivial.

#### 8.4.5 Real LLM Reasoning Support

If `ChatAnthropic` is configured with `extended_thinking=True`, the library automatically:

1. Detects reasoning tokens in `on_chat_model_stream` events
2. Emits `REASONING_START`, `REASONING_MESSAGE_START`, `REASONING_MESSAGE_CONTENT`, `REASONING_MESSAGE_END`, `REASONING_END` events
3. Handles 4 provider formats (Anthropic extended thinking, Anthropic redacted thinking, OpenAI reasoning, generic)

```python
# utils.py — resolve_reasoning_content()
if isinstance(chunk, AIMessageChunk):
    content = resolve_reasoning_content(chunk)
    if content:
        # emit reasoning events
```

The segment agent's reasoning is **simulated** (hardcoded strings from `NODE_META`). To get real LLM reasoning in the segment agent, you'd need to manually parse `AIMessageChunk` objects and emit reasoning events — roughly 40-50 lines of code per reasoning stream. The library does this automatically.

#### 8.4.6 Message Format Conversion

The library provides bidirectional message conversion (`agui_messages_to_langchain()` and `langchain_messages_to_agui()`) including:

- Role mapping (user ↔ human, assistant ↔ ai)
- Multimodal content (base64 images, URLs)
- Tool calls and tool results
- Message ID preservation

The segment agent implements a simpler version in `EventEmitter.langchain_messages_to_agui()` (events.py, 30 lines). The library's version (~100 lines in utils.py) handles more edge cases.

#### 8.4.7 Time-Travel and Interrupt/Resume

The library supports:

- **Time-travel**: `get_checkpoint_before_message()` rewinds graph state to before a specific message, enabling edit-and-regenerate workflows
- **Interrupt/resume**: `Command(resume=...)` handling for human-in-the-loop patterns

Neither feature is used by the template agent currently, but they're available without additional code. The segment agent would need significant manual implementation to support either.

### 8.5 Code Volume Comparison

| Component | Segment Agent | Template Agent | Delta |
|---|---|---|---|
| **Graph definition** | 355 lines (`graph.py`) | 255 lines (`graph.py`) | -100 lines (no `NODE_META`, simpler nodes) |
| **Routes / endpoint** | 546 lines (`routes.py`) | 358 lines (`routes.py`) | -188 lines |
| **Event infrastructure** | 253 lines (`events.py`) — shared EventEmitter | 113 lines (`event_adapter.py`) — template-specific | -140 lines (but EventAdapter is additional to EventEmitter) |
| **Pipeline orchestration** | ~170 lines in `run_segment_pipeline()` | 0 lines (library handles) | -170 lines |
| **Node metadata** | 115 lines (`NODE_META` dict) | 0 lines | -115 lines |
| **Custom event wiring** | 0 lines (events emitted directly) | 22 lines (`_translate_custom()`) | +22 lines |
| **State filtering** | 0 lines (emit exactly what you want) | 15 lines (EventAdapter STATE_SNAPSHOT filtering) | +15 lines |
| **Total endpoint-specific** | ~900 lines | ~615 lines | **-285 lines (~32% less)** |

The template agent saves ~285 lines, but this includes the loss of multi-step progress, reasoning panels, and incremental state deltas. If equivalent features were added (requiring library workarounds), the savings would shrink significantly.

### 8.6 Frontend Impact

| Aspect | Segment Frontend | Template Frontend |
|---|---|---|
| **Hooks used** | `useCoAgent`, `useCoAgentStateRender`, `useCopilotAction`, `useState`, `useEffect` | `useCoAgent`, `useCoAgentStateRender` |
| **Local state** | `progressStatus` (node/index/total tracking) | None |
| **Custom action handler** | `update_progress_status` (intercepts fake tool calls) | None |
| **Main content area** | `<ProgressStatus>` + `<SegmentCard>` | `<TemplateEditor>` + `<TemplatePreview>` |
| **Message rendering** | Complex filtering (checks for newer user/assistant/same-role messages) | Simpler filtering (checks for newer assistant messages) |
| **State render callback** | Returns `null` (card shown inline via `InlineSegmentCard`) | Returns green banner with subject line |
| **Lines of code** | ~120 lines | ~95 lines |

The template frontend is simpler, but this is partly because it lacks features (no progress bar, no inline state cards). The `TemplateEditor`/`TemplatePreview` components add ~80 lines for the editable iframe, which is domain-specific rather than agent-protocol related.

### 8.7 Verdict: When Each Approach Wins

**Use manual event emission (segment pattern) when:**
- You need granular control over UX timing (simulated reasoning with delays, step-by-step progress)
- The pipeline has multiple visible stages that the user should see progressing
- You need incremental state updates (JSON Patch deltas) during processing
- You want to emit fake tool calls for frontend `useCopilotAction` handlers
- Full event replay on reconnection matters (Redis List persistence)

**Use ag-ui-langgraph (template pattern) when:**
- The agent is a simple LLM call (or few nodes) where intermediate UX isn't critical
- You want real LLM features for free (text streaming, reasoning from extended thinking, message conversion)
- You plan to use tool-calling agents where state snapshot suppression matters
- You want time-travel or interrupt/resume without manual implementation
- Reducing boilerplate is a priority and the EventAdapter workarounds are acceptable

**Hybrid approach** (not yet implemented but viable):
- Use `ag-ui-langgraph` for the LLM interaction layer (message conversion, run lifecycle, tool handling)
- Supplement with `adispatch_custom_event()` for step progress, translated by EventAdapter
- Use `ManuallyEmitState` custom events for incremental state deltas
- Accept that simulated reasoning requires either real extended thinking or bypassing the library for those events
