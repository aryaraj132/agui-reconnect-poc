# ag-ui-langgraph v0.0.29 -- Complete Library Walkthrough

> **Source:** [github.com/ag-ui-protocol/ag-ui](https://github.com/ag-ui-protocol/ag-ui) -> `integrations/langgraph/python/`
> **PyPI:** [pypi.org/project/ag-ui-langgraph](https://pypi.org/project/ag-ui-langgraph/)
> **Maintainer:** CopilotKit (Ran Shem Tov)
> **License:** Part of the AG-UI Protocol monorepo

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
- [2. Architecture and Data Flow](#2-architecture-and-data-flow)
  - [2.1 High-Level Architecture](#21-high-level-architecture)
  - [2.2 Event Flow Diagram](#22-event-flow-diagram)
  - [2.3 File Map](#23-file-map)
- [3. Root Configuration](#3-root-configuration)
  - [3.1 pyproject.toml](#31-pyprojecttoml)
- [4. Core Source Code](#4-core-source-code)
  - [4.1 \_\_init\_\_.py -- Public API Surface](#41-__init__py----public-api-surface)
  - [4.2 types.py -- Internal Type Definitions](#42-typespy----internal-type-definitions)
    - [4.2.1 LangGraphEventTypes Enum](#421-langgrapheventtypes-enum)
    - [4.2.2 CustomEventNames Enum](#422-customeventnames-enum)
    - [4.2.3 RunMetadata TypedDict](#423-runmetadata-typeddict)
    - [4.2.4 MessageInProgress TypedDict](#424-messageinprogress-typeddict)
    - [4.2.5 SchemaKeys TypedDict](#425-schemakeys-typeddict)
    - [4.2.6 LangGraph Platform Message Types](#426-langgraph-platform-message-types)
    - [4.2.7 PredictStateTool and LangGraphReasoning](#427-predictstatetool-and-langgraphreasoning)
  - [4.3 agent.py -- LangGraphAgent (Core Class)](#43-agentpy----langgraphagent-core-class)
    - [4.3.1 Constructor and Instance State](#431-constructor-and-instance-state)
    - [4.3.2 clone() -- Per-Request Isolation](#432-clone----per-request-isolation)
    - [4.3.3 run() -- Public Entry Point](#433-run----public-entry-point)
    - [4.3.4 \_handle\_stream\_events() -- The Core Event Loop](#434-_handle_stream_events----the-core-event-loop)
    - [4.3.5 prepare\_stream() -- State Merging and Stream Setup](#435-prepare_stream----state-merging-and-stream-setup)
    - [4.3.6 prepare\_regenerate\_stream() -- Time-Travel](#436-prepare_regenerate_stream----time-travel)
    - [4.3.7 \_handle\_single\_event() -- Per-Event Dispatch](#437-_handle_single_event----per-event-dispatch)
    - [4.3.8 handle\_node\_change() and Step Management](#438-handle_node_change-and-step-management)
    - [4.3.9 langgraph\_default\_merge\_state() -- State Reconciliation](#439-langgraph_default_merge_state----state-reconciliation)
    - [4.3.10 get\_state\_snapshot() -- Output Filtering](#4310-get_state_snapshot----output-filtering)
    - [4.3.11 get\_stream\_kwargs() -- Version-Safe Streaming](#4311-get_stream_kwargs----version-safe-streaming)
    - [4.3.12 State Snapshot Suppression Logic](#4312-state-snapshot-suppression-logic)
  - [4.4 utils.py -- Message Conversion and Serialization](#44-utilspy----message-conversion-and-serialization)
    - [4.4.1 Message Conversion: AG-UI to LangChain](#441-message-conversion-ag-ui-to-langchain)
    - [4.4.2 Message Conversion: LangChain to AG-UI](#442-message-conversion-langchain-to-ag-ui)
    - [4.4.3 Multimodal Content Conversion](#443-multimodal-content-conversion)
    - [4.4.4 Reasoning Content Resolution](#444-reasoning-content-resolution)
    - [4.4.5 make\_json\_safe() -- Deep Serialization](#445-make_json_safe----deep-serialization)
    - [4.4.6 Utility Helpers](#446-utility-helpers)
- [5. Endpoint and Middleware](#5-endpoint-and-middleware)
  - [5.1 endpoint.py -- FastAPI Integration](#51-endpointpy----fastapi-integration)
  - [5.2 middlewares/state\_streaming.py -- StateStreamingMiddleware](#52-middlewaresstate_streamingpy----statestreamingmiddleware)
- [6. Tests](#6-tests)
  - [6.1 test\_clone.py](#61-test_clonepy)
  - [6.2 test\_make\_json\_safe.py](#62-test_make_json_safepy)
  - [6.3 test\_multimodal.py](#63-test_multimodalpy)
  - [6.4 test\_state\_streaming\_middleware.py](#64-test_state_streaming_middlewarepy)
- [7. End-to-End Request Lifecycle](#7-end-to-end-request-lifecycle)
  - [7.1 New Chat Message (Happy Path)](#71-new-chat-message-happy-path)
  - [7.2 Reconnection / Time-Travel](#72-reconnection--time-travel)
  - [7.3 Interrupt and Resume](#73-interrupt-and-resume)

---

## 1. Project Overview

`ag-ui-langgraph` is a Python library that bridges **LangGraph** (LangChain's stateful agent orchestration framework) with the **AG-UI protocol** (an open, event-based protocol for connecting AI agents to user-facing applications).

The library solves a specific problem: LangGraph emits low-level internal events via `graph.astream_events()` (chain starts, chat model streams, tool starts, etc.), while AG-UI clients (like CopilotKit) expect a standardized set of events (`RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`, `STATE_SNAPSHOT`, etc.). This library translates between the two.

**What it does:**
- Wraps any compiled `StateGraph` and exposes it as an AG-UI-compatible async event stream
- Translates LangGraph's `astream_events(version="v2")` output into AG-UI event objects
- Handles message format conversion between AG-UI messages and LangChain messages
- Manages per-request state tracking (active runs, in-progress messages, node transitions)
- Supports advanced features: time-travel regeneration, interrupt/resume, reasoning/thinking streams, predict_state tool call optimization, multimodal messages
- Provides a one-line FastAPI endpoint helper and a middleware for predict_state streaming

**What it does NOT do:**
- Stream reconnection or replay (no built-in mechanism for catching up missed events)
- Persistent storage (relies on LangGraph's checkpointer for state persistence)
- Redis/Pub-Sub integration (the consuming application must handle transport)

**Dependencies:**

| Package | Version | Purpose |
|---------|---------|---------|
| `ag-ui-protocol` | `>=0.1.10` | AG-UI event types, encoder, core protocol types |
| `langchain` | `>=1.2.0` | Message types (fallback import path) |
| `langchain-core` | `>=0.3.0` | Message types, RunnableConfig, runnable context |
| `langgraph` | `>=0.3.25,<1.1.0` | CompiledStateGraph, Command, astream_events |
| `pydantic` | `>=2.0.0` | Model serialization (via ag-ui-protocol) |
| `fastapi` | `>=0.115.12` | Optional: endpoint helper |

---

## 2. Architecture and Data Flow

### 2.1 High-Level Architecture

The library sits between a LangGraph compiled graph and an AG-UI client (e.g., CopilotKit frontend). The `LangGraphAgent` class is the central mediator:

```
+------------------+        +-------------------+        +------------------+
|  AG-UI Client    |  HTTP  |   Your FastAPI    |        |   LangGraph      |
|  (CopilotKit)    | -----> |   Application     |        |   StateGraph     |
|                  |        |                   |        |                  |
|  Sends:          |        |  Creates:         |        |  Provides:       |
|  RunAgentInput   |        |  LangGraphAgent   |        |  astream_events()|
|  (messages,      |        |                   |        |  aget_state()    |
|   state, tools)  |        |  Calls:           |        |  aupdate_state() |
|                  |        |  agent.run(input)  |        |                  |
|  Receives:       |        |                   |        |  Emits:          |
|  SSE stream of   | <----- |  Yields:          | <----- |  on_chain_*      |
|  AG-UI events    |        |  AG-UI events     |        |  on_chat_model_* |
+------------------+        +-------------------+        |  on_tool_*       |
                                                         |  on_custom_event |
                                                         +------------------+
```

### 2.2 Event Flow Diagram

A single `agent.run(input)` call produces this event sequence:

```
LangGraph astream_events()          LangGraphAgent                    AG-UI Client
─────────────────────────           ──────────────                    ────────────
                                    RUN_STARTED ──────────────────>   run begins
                                    
on_chain_start (node="generate")    STEP_STARTED("generate") ─────>  step indicator
                                    
on_chat_model_stream (chunk)   ──>  TEXT_MESSAGE_START ────────────>  new bubble
on_chat_model_stream (chunk)   ──>  TEXT_MESSAGE_CONTENT("Hel") ──>  append text
on_chat_model_stream (chunk)   ──>  TEXT_MESSAGE_CONTENT("lo") ───>  append text
on_chat_model_stream (finish)       (skipped -- finish_reason set)
on_chat_model_end              ──>  TEXT_MESSAGE_END ──────────────>  close bubble
                                    
on_chain_end (output={...})    ──>  STATE_SNAPSHOT({...}) ─────────>  update state
                                    STEP_FINISHED("generate") ────>  step done
                                    
                              aget_state() ──>
                                    STATE_SNAPSHOT (final) ────────>  final state
                                    MESSAGES_SNAPSHOT ─────────────>  full history
                                    RUN_FINISHED ─────────────────>  run complete
```

### 2.3 File Map

```
ag_ui_langgraph/
  __init__.py                  Public API surface (re-exports)
  agent.py                     LangGraphAgent class (~1173 lines, core logic)
  types.py                     TypedDicts and Enums for internal state
  utils.py                     Message conversion, serialization helpers
  endpoint.py                  add_langgraph_fastapi_endpoint() helper
  middlewares/
    __init__.py                Package docstring
    state_streaming.py         StateStreamingMiddleware for predict_state
tests/
  __init__.py
  test_clone.py                Tests for LangGraphAgent.clone() subclass preservation
  test_make_json_safe.py       Tests for deep JSON serialization
  test_multimodal.py           Tests for multimodal message conversion
  test_state_streaming_middleware.py  Tests for StateStreamingMiddleware
```

---

## 3. Root Configuration

### 3.1 pyproject.toml

```toml
[project]
name = "ag-ui-langgraph"
version = "0.0.29"
description = "Implementation of the AG-UI protocol for LangGraph."
authors = [
    { name = "Ran Shem Tov", email = "ran@copilotkit.ai" }
]
requires-python = ">=3.10,<3.14"
dependencies = [
    "ag-ui-protocol>=0.1.10",
    "langchain>=1.2.0",
    "langchain-core>=0.3.0",
    "langgraph>=0.3.25,<1.1.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
fastapi = ["fastapi>=0.115.12"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["ag_ui_langgraph"]
exclude = ["examples/**"]
```

Key observations:
- The `fastapi` dependency is optional -- `endpoint.py` is only usable when `fastapi` is installed.
- The `langgraph` upper bound (`<1.1.0`) pins to the v0.x/1.0.x API. The library relies on `astream_events(version="v2")` which could change in a major version.
- The `langchain` import has a fallback: tries `langchain.schema` first, then `langchain_core.messages`. This supports both `langchain<1.0.0` and `>=1.0.0`.
- Examples are excluded from the wheel build.

---

## 4. Core Source Code

### 4.1 \_\_init\_\_.py -- Public API Surface

The package re-exports everything consumers need:

```python
from .agent import LangGraphAgent
from .types import (
    LangGraphEventTypes, CustomEventNames, State, SchemaKeys,
    MessageInProgress, RunMetadata, MessagesInProgressRecord,
    ToolCall, BaseLangGraphPlatformMessage,
    LangGraphPlatformResultMessage,
    LangGraphPlatformActionExecutionMessage,
    LangGraphPlatformMessage, PredictStateTool
)
from .endpoint import add_langgraph_fastapi_endpoint
from .middlewares.state_streaming import StateStreamingMiddleware, StateItem
```

The primary public API is:
- **`LangGraphAgent`** -- the main class (instantiate, call `.run()`)
- **`add_langgraph_fastapi_endpoint`** -- one-liner to mount an agent on a FastAPI app
- **`StateStreamingMiddleware` / `StateItem`** -- middleware for predict_state streaming
- **Type exports** -- for consumers who need to type-check or extend

---

### 4.2 types.py -- Internal Type Definitions

This file defines TypedDicts and Enums used by the agent. These are internal tracking structures, not part of the AG-UI protocol itself.

#### 4.2.1 LangGraphEventTypes Enum

Maps LangGraph's `astream_events()` event type strings to an enum:

```python
class LangGraphEventTypes(str, Enum):
    OnChainStart = "on_chain_start"
    OnChainStream = "on_chain_stream"
    OnChainEnd = "on_chain_end"
    OnChatModelStart = "on_chat_model_start"
    OnChatModelStream = "on_chat_model_stream"
    OnChatModelEnd = "on_chat_model_end"
    OnToolStart = "on_tool_start"
    OnToolEnd = "on_tool_end"
    OnCustomEvent = "on_custom_event"
    OnInterrupt = "on_interrupt"
```

These correspond 1:1 to LangGraph's v2 streaming event types. The agent uses these to pattern-match incoming events and decide which AG-UI events to emit.

#### 4.2.2 CustomEventNames Enum

Special event names that can be dispatched via `adispatch_custom_event()` from inside graph nodes:

```python
class CustomEventNames(str, Enum):
    ManuallyEmitMessage = "manually_emit_message"
    ManuallyEmitToolCall = "manually_emit_tool_call"
    ManuallyEmitState = "manually_emit_state"
    Exit = "exit"
```

These provide an escape hatch: graph nodes can emit AG-UI events directly without going through the normal LLM streaming path. For example, `manually_emit_state` causes an immediate `STATE_SNAPSHOT` emission, and `exit` signals the agent to stop processing.

#### 4.2.3 RunMetadata TypedDict

Per-run mutable state tracked during `_handle_stream_events()`:

```python
RunMetadata = TypedDict("RunMetadata", {
    "id": str,                              # Current run_id
    "schema_keys": NotRequired[...],        # Input/output schema keys for filtering
    "node_name": NotRequired[...],          # Currently executing graph node
    "prev_node_name": NotRequired[...],     # Previous node (for transition detection)
    "exiting_node": NotRequired[bool],      # Whether the current node is finishing
    "manually_emitted_state": NotRequired[...],  # State set by ManuallyEmitState
    "thread_id": NotRequired[...],          # Thread ID for checkpointing
    "reasoning_process": NotRequired[...],  # Active thinking/reasoning stream
    "has_function_streaming": NotRequired[bool],  # Tool call was streamed chunk-by-chunk
    "model_made_tool_call": NotRequired[bool],    # Predict_state tool detected
    "state_reliable": NotRequired[bool],          # Whether current_graph_state is trustworthy
})
```

The `state_reliable` flag is particularly important. When a predict_state tool call is detected, the agent sets `state_reliable = False` because `current_graph_state` does not yet reflect the tool's output. This prevents emitting a stale `STATE_SNAPSHOT` that would overwrite progress already pushed to the client.

#### 4.2.4 MessageInProgress TypedDict

Tracks the currently-streaming message (text or tool call):

```python
MessageInProgress = TypedDict("MessageInProgress", {
    "id": str,                                  # Message ID (from AIMessage chunk)
    "tool_call_id": NotRequired[Optional[str]], # Set if this is a tool call stream
    "tool_call_name": NotRequired[Optional[str]]
})
```

The agent maintains `messages_in_process: Dict[str, Optional[MessageInProgress]]` keyed by `run_id`. This allows detecting transitions: when a streaming text message ends and a tool call begins, or vice versa.

#### 4.2.5 SchemaKeys TypedDict

Determines which keys from the graph state should be included in various payloads:

```python
SchemaKeys = TypedDict("SchemaKeys", {
    "input": NotRequired[Optional[List[str]]],   # Keys for input state
    "output": NotRequired[Optional[List[str]]],  # Keys for STATE_SNAPSHOT
    "config": NotRequired[Optional[List[str]]],  # Graph config keys
    "context": NotRequired[Optional[List[str]]]  # Context schema keys
})
```

These are derived from the graph's JSON schema at runtime via `get_schema_keys()`. The `output` keys determine what appears in `STATE_SNAPSHOT` events -- keys like `messages` and `tools` are always included via `constant_schema_keys`.

#### 4.2.6 LangGraph Platform Message Types

Three TypedDicts model the message format used by LangGraph Platform (the hosted version):

```python
class BaseLangGraphPlatformMessage(TypedDict):
    content: str
    role: str
    additional_kwargs: NotRequired[Dict[str, Any]]
    type: str
    id: str

class LangGraphPlatformResultMessage(BaseLangGraphPlatformMessage):
    tool_call_id: str
    name: str

class LangGraphPlatformActionExecutionMessage(BaseLangGraphPlatformMessage):
    tool_calls: List[ToolCall]
```

These are used for type hints when handling messages that come from the LangGraph Platform API rather than local graph execution.

#### 4.2.7 PredictStateTool and LangGraphReasoning

```python
PredictStateTool = TypedDict("PredictStateTool", {
    "tool": str,          # Tool name that produces state predictions
    "state_key": str,     # Which state key to update
    "tool_argument": str  # Which tool argument contains the state value
})

LangGraphReasoning = TypedDict("LangGraphReasoning", {
    "type": str,          # Always "text" for now
    "text": str,          # The reasoning content
    "index": int,         # Reasoning step index
    "signature": NotRequired[Optional[str]],  # Anthropic thinking signature
})
```

`PredictStateTool` defines how the agent detects and handles tool calls that should produce incremental state updates. `LangGraphReasoning` captures thinking/reasoning content from models that support it (Anthropic extended thinking, OpenAI reasoning).

---

### 4.3 agent.py -- LangGraphAgent (Core Class)

This is the heart of the library at ~1173 lines. The `LangGraphAgent` class wraps a compiled `StateGraph` and translates its event stream into AG-UI events.

#### 4.3.1 Constructor and Instance State

```python
class LangGraphAgent:
    def __init__(
        self,
        *,
        name: str,
        graph: CompiledStateGraph,
        description: Optional[str] = None,
        config: Union[Optional[RunnableConfig], dict] = None
    ):
        self.name = name
        self.description = description
        self.graph = graph
        self.config = config or {}
        self.messages_in_process: MessagesInProgressRecord = {}
        self.active_run: Optional[RunMetadata] = None
        self.constant_schema_keys = ['messages', 'tools']
```

- `graph` is the compiled LangGraph `StateGraph`. The agent never modifies the graph definition -- it only calls `astream_events()`, `aget_state()`, and `aupdate_state()` on it.
- `config` is the base `RunnableConfig` passed to all graph operations. It typically contains `recursion_limit` or model overrides.
- `messages_in_process` tracks which messages are currently being streamed. Keyed by `run_id`.
- `active_run` holds the mutable per-run metadata (`RunMetadata`). It is set at the start of `_handle_stream_events()` and cleared at the end.
- `constant_schema_keys` ensures `messages` and `tools` are always included in state payloads regardless of the graph's schema.

**Important:** `active_run` is mutable instance state. This means a single `LangGraphAgent` instance cannot safely handle concurrent requests. Each concurrent request must use a separate instance via `clone()`.

#### 4.3.2 clone() -- Per-Request Isolation

```python
def clone(self) -> Self:
    try:
        return type(self)(
            name=self.name,
            graph=self.graph,
            description=self.description,
            config=dict(self.config) if self.config else None,
        )
    except TypeError as exc:
        raise TypeError(
            f"{type(self).__name__} must override clone() or ensure its "
            f"__init__ accepts (name, graph, description, config) as "
            f"keyword arguments: {exc}"
        ) from exc
```

`clone()` creates a fresh instance of the same class (preserving subclass identity via `type(self)`) with clean `messages_in_process` and `active_run` state. The `graph` reference is shared (not deep-copied) since it is immutable after compilation. The `config` dict is shallow-copied to prevent mutation leakage.

If a subclass adds required `__init__` parameters beyond the base four, `clone()` raises a `TypeError` with a clear message telling the developer to override `clone()`.

#### 4.3.3 run() -- Public Entry Point

```python
async def run(self, input: RunAgentInput) -> AsyncGenerator[str, None]:
    forwarded_props = {}
    if hasattr(input, "forwarded_props") and input.forwarded_props:
        forwarded_props = {
            camel_to_snake(k): v for k, v in input.forwarded_props.items()
        }
    async for event_str in self._handle_stream_events(
        input.copy(update={"forwarded_props": forwarded_props})
    ):
        yield event_str
```

`run()` is a thin wrapper that:
1. Converts `forwarded_props` keys from camelCase (as sent by CopilotKit) to snake_case (as used by Python)
2. Delegates to `_handle_stream_events()`
3. Yields AG-UI event objects (not strings -- despite the type annotation saying `str`, it actually yields event dataclass instances)

The `RunAgentInput` type (from `ag_ui.core`) contains:
- `thread_id`: Identifies the conversation thread
- `run_id`: Unique ID for this run
- `messages`: Array of AG-UI messages (user, assistant, tool)
- `state`: Frontend state to merge into graph state
- `tools`: Frontend-defined tools (CopilotKit actions)
- `context`: Additional context
- `forwarded_props`: Arbitrary props forwarded from CopilotKit

#### 4.3.4 \_handle\_stream\_events() -- The Core Event Loop

This is the largest method (~160 lines). It orchestrates the full lifecycle of a single run:

```python
async def _handle_stream_events(self, input: RunAgentInput) -> AsyncGenerator[str, None]:
    thread_id = input.thread_id or str(uuid.uuid4())

    # 1. Initialize per-run state
    INITIAL_ACTIVE_RUN = {
        "id": input.run_id,
        "thread_id": thread_id,
        "reasoning_process": None,
        "node_name": None,
        "has_function_streaming": False,
        "model_made_tool_call": False,
        "state_reliable": True,
        "streamed_messages": [],
    }
    self.active_run = INITIAL_ACTIVE_RUN
```

Phase 1 -- **Initialization**: Sets up `active_run` with defaults. `state_reliable` starts `True` and only becomes `False` when a predict_state tool call is detected before the tool executes.

```python
    # 2. Prepare the stream (state merge, input resolution)
    prepared_stream_response = await self.prepare_stream(
        input=input, agent_state=agent_state, config=config
    )

    # 3. Emit RUN_STARTED
    yield self._dispatch_event(
        RunStartedEvent(type=EventType.RUN_STARTED,
                        thread_id=thread_id,
                        run_id=self.active_run["id"])
    )
```

Phase 2 -- **Preparation**: Calls `prepare_stream()` which reads the checkpointer, merges state, and returns the event stream. If the graph has active interrupts, `prepare_stream()` returns pre-built events and no stream.

Phase 3 -- **Event emission**: Emits `RUN_STARTED` and begins processing.

```python
    # 4. Main event loop
    async for event in stream:
        # ... detect node changes, track tool calls ...

        # STATE_SNAPSHOT on node exit (with suppression logic)
        suppressed = exiting_node and (mmtc or not state_reliable)
        if not suppressed:
            yield self._dispatch_event(
                StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, ...)
            )

        # Always emit RAW event
        yield self._dispatch_event(RawEvent(type=EventType.RAW, event=event))

        # Dispatch to per-event-type handler
        async for single_event in self._handle_single_event(event, state):
            yield single_event
```

Phase 4 -- **Main loop**: Iterates over `graph.astream_events()`. For each raw LangGraph event:
- Detects node name changes and emits `STEP_STARTED`/`STEP_FINISHED`
- Tracks whether a predict_state tool call was made (`model_made_tool_call`)
- Emits `STATE_SNAPSHOT` on node exit (unless suppressed)
- Always emits a `RAW` event (the original LangGraph event, for debugging)
- Delegates to `_handle_single_event()` for type-specific processing

```python
    # 5. Post-stream finalization
    state = await self.graph.aget_state(config)
    # ... handle interrupts ...
    yield self._dispatch_event(
        StateSnapshotEvent(type=EventType.STATE_SNAPSHOT,
                           snapshot=self.get_state_snapshot(state_values))
    )
    yield self._dispatch_event(
        MessagesSnapshotEvent(type=EventType.MESSAGES_SNAPSHOT,
                              messages=langchain_messages_to_agui(snapshot_messages))
    )
    yield self._dispatch_event(
        RunFinishedEvent(type=EventType.RUN_FINISHED, ...)
    )
    self.active_run = None
```

Phase 5 -- **Finalization**: After the stream ends, reads the final checkpointer state, emits a final `STATE_SNAPSHOT`, a `MESSAGES_SNAPSHOT` (full message history), and `RUN_FINISHED`. The `active_run` is cleared.

#### 4.3.5 prepare\_stream() -- State Merging and Stream Setup

`prepare_stream()` is the most complex preparation method (~110 lines). It handles four scenarios:

**Scenario 1 -- Normal start (new messages):**
```python
state_input["messages"] = agent_state.values.get("messages", [])
langchain_messages = agui_messages_to_langchain(messages)
state = self.langgraph_default_merge_state(state_input, langchain_messages, input)
stream = self.graph.astream_events(**kwargs)
return {"stream": stream, "state": state, "config": config}
```

Converts AG-UI messages to LangChain format, merges them with existing checkpoint messages, and starts the stream.

**Scenario 2 -- Time-travel regeneration:**
```python
if len(agent_state.values.get("messages", [])) > len(non_system_messages):
    # Check if incoming messages are already in checkpoint
    if not is_continuation:
        return await self.prepare_regenerate_stream(...)
```

When the checkpoint has more messages than the incoming request (and the incoming messages aren't just a continuation), this indicates the user edited a previous message. The agent forks the checkpoint history and regenerates from that point.

**Scenario 3 -- Active interrupts without resume:**
```python
if has_active_interrupts and not resume_input:
    events_to_dispatch = [
        RunStartedEvent(...),
        CustomEvent(name="on_interrupt", value=interrupt.value),
        RunFinishedEvent(...),
    ]
    return {"stream": None, "events_to_dispatch": events_to_dispatch}
```

When the graph has pending interrupts and no resume input, the agent immediately emits the interrupt events without starting a new stream.

**Scenario 4 -- Resume after interrupt:**
```python
if resume_input:
    stream_input = Command(resume=resume_input)
```

Wraps the resume value in a LangGraph `Command` object to resume execution after an interrupt.

#### 4.3.6 prepare\_regenerate\_stream() -- Time-Travel

```python
async def prepare_regenerate_stream(self, input, message_checkpoint, config):
    # Find the checkpoint BEFORE the edited message
    time_travel_checkpoint = await self.get_checkpoint_before_message(
        message_checkpoint.id, thread_id, config
    )

    # Fork the checkpoint
    fork = await self.graph.aupdate_state(
        time_travel_checkpoint.config,
        time_travel_checkpoint.values,
        as_node=time_travel_checkpoint.next[0] if time_travel_checkpoint.next else "__start__"
    )

    # Start a new stream from the fork point
    stream_input = self.langgraph_default_merge_state(
        time_travel_checkpoint.values, [message_checkpoint], input
    )
    stream = self.graph.astream_events(**kwargs)
    return {"stream": stream, "state": time_travel_checkpoint.values, "config": config}
```

This is LangGraph's time-travel feature. The agent:
1. Walks the checkpoint history to find the state just before the edited message
2. Forks the checkpoint at that point via `aupdate_state()`
3. Starts a new stream with the edited message

`get_checkpoint_before_message()` iterates through `graph.aget_state_history()` to find the checkpoint snapshot that contains the target message ID, then returns the snapshot at `idx - 1`.

#### 4.3.7 \_handle\_single\_event() -- Per-Event Dispatch

This method (~180 lines) handles each individual LangGraph event type:

**`on_chat_model_stream` -- Text and tool call streaming:**

```python
if event_type == LangGraphEventTypes.OnChatModelStream:
    # Skip finish_reason chunks
    if event["data"]["chunk"].response_metadata.get('finish_reason', None):
        return

    tool_call_data = event["data"]["chunk"].tool_call_chunks[0] if ... else None
    message_content = resolve_message_content(event["data"]["chunk"].content)
```

For each streaming chunk, the method determines whether it is:
- **Tool call start**: First chunk with a tool call name and no active stream -> `TOOL_CALL_START`
- **Tool call args**: Active tool call stream + args delta -> `TOOL_CALL_ARGS`
- **Tool call end**: Active tool call stream + no more tool data -> `TOOL_CALL_END`
- **Text message start**: No active stream + text content -> `TEXT_MESSAGE_START`
- **Text message content**: Active text stream + content -> `TEXT_MESSAGE_CONTENT`
- **Text message end**: Active text stream + no content -> `TEXT_MESSAGE_END`
- **Reasoning content**: Thinking/reasoning block -> `REASONING_START/CONTENT/END`

The method also detects **predict_state** tool calls by checking `event.metadata["predict_state"]`:

```python
predict_state_metadata = event.get("metadata", {}).get("predict_state", [])
tool_call_used_to_predict_state = any(
    p.get("tool") == tool_call_data["name"]
    for p in predict_state_metadata
)
if tool_call_used_to_predict_state:
    yield CustomEvent(type=EventType.CUSTOM, name="PredictState",
                      value=predict_state_metadata)
```

**`on_chat_model_end` -- Model turn completion:**

```python
elif event_type == LangGraphEventTypes.OnChatModelEnd:
    output_msg = event.get("data", {}).get("output")
    if isinstance(output_msg, BaseMessage):
        self.active_run.setdefault("streamed_messages", []).append(output_msg)
    # Close any open message or tool call stream
    if self.get_message_in_progress(...)["tool_call_id"]:
        yield ToolCallEndEvent(...)
    elif self.get_message_in_progress(...)["id"]:
        yield TextMessageEndEvent(...)
```

Ensures any open message stream is properly closed and appends the full output message to `streamed_messages` for the final `MESSAGES_SNAPSHOT`.

**`on_custom_event` -- Manual emissions:**

```python
elif event_type == LangGraphEventTypes.OnCustomEvent:
    if event["name"] == CustomEventNames.ManuallyEmitMessage:
        yield TextMessageStartEvent(...)
        yield TextMessageContentEvent(...)
        yield TextMessageEndEvent(...)
    elif event["name"] == CustomEventNames.ManuallyEmitToolCall:
        yield ToolCallStartEvent(...)
        yield ToolCallArgsEvent(...)
        yield ToolCallEndEvent(...)
    elif event["name"] == CustomEventNames.ManuallyEmitState:
        self.active_run["manually_emitted_state"] = event["data"]
        yield StateSnapshotEvent(...)
    # Always emit the custom event too
    yield CustomEvent(...)
```

Custom events provide a way for graph nodes to directly control AG-UI event emission. A node can call `adispatch_custom_event("manually_emit_message", {"message_id": "...", "message": "..."})` to emit a complete text message without going through the LLM streaming path.

**`on_tool_end` -- Tool execution results:**

```python
elif event_type == LangGraphEventTypes.OnToolEnd:
    tool_call_output = event["data"]["output"]

    if isinstance(tool_call_output, Command):
        # Extract ToolMessages from Command.update
        messages = tool_call_output.update.get('messages', [])
        for tool_msg in [m for m in messages if isinstance(m, ToolMessage)]:
            if not self.active_run["has_function_streaming"]:
                yield ToolCallStartEvent(...)  # Emit start/args/end
            yield ToolCallResultEvent(
                tool_call_id=tool_msg.tool_call_id,
                content=normalize_tool_content(tool_msg.content),
            )
    else:
        # Standard ToolMessage output
        if not self.active_run["has_function_streaming"]:
            yield ToolCallStartEvent(...)
        yield ToolCallResultEvent(...)

    self.active_run["model_made_tool_call"] = False
    self.active_run["state_reliable"] = True
```

After a tool finishes, the agent emits `TOOL_CALL_RESULT` with the tool's output. If `has_function_streaming` is `True`, the `TOOL_CALL_START`/`ARGS`/`END` events were already emitted during streaming, so only the result is emitted. After the tool runs, `state_reliable` is reset to `True` because the graph state now reflects the tool's output.

The method also handles `Command` return values from tools -- a LangGraph pattern where a tool returns a `Command` object to update state and route the graph.

#### 4.3.8 handle\_node\_change() and Step Management

```python
def handle_node_change(self, node_name: Optional[str]):
    if node_name == "__end__":
        node_name = None

    if node_name != self.active_run.get("node_name"):
        if self.active_run.get("node_name"):
            yield self.end_step()
        if node_name:
            for event in self.start_step(node_name):
                yield event

    self.active_run["node_name"] = node_name
```

Centralized step transition management. When the LangGraph node changes:
1. End the previous step (`STEP_FINISHED`)
2. Start the new step (`STEP_STARTED`)
3. Update `active_run["node_name"]`

The `__end__` node is normalized to `None` since it represents graph completion, not a real step. This is called:
- At the start of stream processing (for the initial node)
- During the main loop when `event.metadata.langgraph_node` changes
- After the stream ends (for the final `__end__` transition)

#### 4.3.9 langgraph\_default\_merge\_state() -- State Reconciliation

This method (~90 lines) merges incoming AG-UI messages with existing checkpoint messages:

```python
def langgraph_default_merge_state(self, state, messages, input):
    # 1. Strip system messages from incoming (they're in the graph prompt)
    if messages and isinstance(messages[0], SystemMessage):
        messages = messages[1:]

    existing_messages = state.get("messages", [])

    # 2. Fix string args in tool_calls (Bedrock compatibility)
    for msg in existing_messages:
        if isinstance(msg, AIMessage) and getattr(msg, 'tool_calls', None):
            for tc in msg.tool_calls:
                if isinstance(tc.get('args'), str):
                    tc['args'] = json.loads(tc['args'])

    # 3. Fix orphan ToolMessages
    # (Replace fake content from patch_orphan_tool_calls with real AG-UI content)
    agui_tool_content = {
        m.tool_call_id: m.content
        for m in messages if isinstance(m, ToolMessage)
    }
    # ... scan and replace orphan messages ...

    # 4. Deduplicate: only add messages not already in checkpoint
    existing_message_ids = {msg.id for msg in existing_messages}
    new_messages = [msg for msg in messages if msg.id not in existing_message_ids]

    # 5. Merge tools (deduplicate by name)
    tools = input.tools or []
    all_tools = [*state.get("tools", []), *tools_as_dicts]
    # ... deduplicate ...

    return {
        **state,
        "messages": new_messages,
        "tools": unique_tools,
        "ag-ui": {"tools": unique_tools, "context": input.context or []},
        "copilotkit": {
            **state.get("copilotkit", {}),
            "actions": unique_tools,
        },
    }
```

Key details:
- **Orphan ToolMessages**: When a tool call is interrupted, LangGraph's checkpointer may contain fake ToolMessages with content like `"Tool call 'X' with id 'Y' was interrupted before completion."`. This method detects these (via `_ORPHAN_TOOL_MSG_RE`) and replaces them with the actual content from the AG-UI messages.
- **Message deduplication**: Only messages with IDs not already in the checkpoint are added. This prevents duplicates when CopilotKit resends the full message history.
- **Tool deduplication**: Tools are deduplicated by name, with the first occurrence winning.
- **CopilotKit compatibility**: The merged state includes both `"ag-ui"` and `"copilotkit"` keys, maintaining backwards compatibility with CopilotKit's older API.

#### 4.3.10 get\_state\_snapshot() -- Output Filtering

```python
def get_state_snapshot(self, state: State) -> State:
    schema_keys = self.active_run["schema_keys"]
    if schema_keys and schema_keys.get("output"):
        state = filter_object_by_schema_keys(
            state, [*DEFAULT_SCHEMA_KEYS, *schema_keys["output"]]
        )
    return state
```

Filters the graph state to only include keys defined in the output schema. This prevents internal graph state (node routing flags, intermediate computation) from leaking to the client. The `DEFAULT_SCHEMA_KEYS` (`["tools"]`) are always included.

#### 4.3.11 get\_stream\_kwargs() -- Version-Safe Streaming

```python
def get_stream_kwargs(self, input, subgraphs=False, version="v2", config=None, context=None, fork=None):
    kwargs = dict(input=input, subgraphs=subgraphs, version=version)

    # Only add context if the method signature supports it
    sig = inspect.signature(self.graph.astream_events)
    if 'context' in sig.parameters:
        base_context = {}
        if isinstance(config, dict) and 'configurable' in config:
            base_context.update(config['configurable'])
        if context:
            base_context.update(context)
        if base_context:
            kwargs['context'] = base_context

    if config:
        kwargs['config'] = config
    return kwargs
```

Uses `inspect.signature` to check whether the installed version of LangGraph supports the `context` parameter in `astream_events()`. This provides backwards compatibility across LangGraph versions -- older versions that lack the `context` parameter simply don't receive it.

#### 4.3.12 State Snapshot Suppression Logic

The agent suppresses `STATE_SNAPSHOT` emissions in specific scenarios to prevent overwriting client-side state:

```python
# In _handle_stream_events main loop:
exiting_node = self.active_run["node_name"] == current_node_name
mmtc = self.active_run.get("model_made_tool_call")
state_reliable = self.active_run.get("state_reliable", True)
suppressed = exiting_node and (mmtc or not state_reliable)
```

| `exiting_node` | `model_made_tool_call` | `state_reliable` | Suppressed? | Why |
|:-:|:-:|:-:|:-:|-----|
| True | True | True | Yes | Predict_state tool detected but not yet run; snapshot would be stale |
| True | False | False | Yes | State was marked unreliable by a prior predict_state detection |
| True | False | True | No | Normal node exit, state is current |
| False | * | * | No | Not exiting a node, no snapshot to suppress |

After suppression, `model_made_tool_call` is reset to `False`, and if it was a predict_state case, `state_reliable` is set to `False` for subsequent events until the tool actually runs.

---

### 4.4 utils.py -- Message Conversion and Serialization

This file (~400 lines) contains stateless utility functions for converting between AG-UI and LangChain message formats, handling multimodal content, and safely serializing complex objects to JSON.

#### 4.4.1 Message Conversion: AG-UI to LangChain

```python
def agui_messages_to_langchain(messages: List[AGUIMessage]) -> List[BaseMessage]:
    langchain_messages = []
    for message in messages:
        role = message.role
        if role == "user":
            # Handle multimodal content
            if isinstance(message.content, str):
                content = message.content
            elif isinstance(message.content, list):
                content = convert_agui_multimodal_to_langchain(message.content)
            langchain_messages.append(HumanMessage(id=message.id, content=content, name=message.name))
        elif role == "assistant":
            tool_calls = []
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments),
                        "type": "tool_call",
                    })
            langchain_messages.append(AIMessage(id=message.id, content=message.content or "", tool_calls=tool_calls))
        elif role == "system":
            langchain_messages.append(SystemMessage(id=message.id, content=message.content))
        elif role == "tool":
            langchain_messages.append(ToolMessage(id=message.id, content=message.content, tool_call_id=message.tool_call_id))
    return langchain_messages
```

The mapping:

| AG-UI Role | LangChain Type | Special Handling |
|------------|---------------|------------------|
| `user` | `HumanMessage` | Multimodal content converted via `convert_agui_multimodal_to_langchain()` |
| `assistant` | `AIMessage` | Tool calls converted from `{function: {name, arguments}}` to `{name, args}` format |
| `system` | `SystemMessage` | Direct mapping |
| `tool` | `ToolMessage` | `tool_call_id` preserved |

#### 4.4.2 Message Conversion: LangChain to AG-UI

The reverse conversion (`langchain_messages_to_agui()`) maps back:

```python
def langchain_messages_to_agui(messages: List[BaseMessage]) -> List[AGUIMessage]:
    for message in messages:
        if isinstance(message, HumanMessage):
            if isinstance(message.content, list):
                content = convert_langchain_multimodal_to_agui(message.content)
            else:
                content = stringify_if_needed(resolve_message_content(message.content))
            agui_messages.append(AGUIUserMessage(id=str(message.id), role="user", content=content))
        elif isinstance(message, AIMessage):
            tool_calls = [
                AGUIToolCall(
                    id=str(tc["id"]),
                    type="function",
                    function=AGUIFunctionCall(
                        name=tc["name"],
                        arguments=json.dumps(tc.get("args", {})),
                    ),
                )
                for tc in message.tool_calls
            ] if message.tool_calls else None
            agui_messages.append(AGUIAssistantMessage(..., tool_calls=tool_calls))
```

Key difference: AG-UI tool calls use the `{type: "function", function: {name, arguments}}` format (OpenAI-compatible), while LangChain uses `{name, args}`. The conversion `json.dumps(tc.get("args", {}))` serializes the args dict back to a JSON string.

#### 4.4.3 Multimodal Content Conversion

Two helper functions handle multimodal (text + image) content:

**AG-UI to LangChain:**
```python
def convert_agui_multimodal_to_langchain(content):
    for item in content:
        if isinstance(item, TextInputContent):
            langchain_content.append({"type": "text", "text": item.text})
        elif isinstance(item, BinaryInputContent):
            if item.url:
                content_dict["image_url"] = {"url": item.url}
            elif item.data:
                content_dict["image_url"] = {"url": f"data:{item.mime_type};base64,{item.data}"}
```

**LangChain to AG-UI:**
```python
def convert_langchain_multimodal_to_agui(content):
    for item in content:
        if item.get("type") == "text":
            agui_content.append(TextInputContent(type="text", text=item.get("text", "")))
        elif item.get("type") == "image_url":
            url = image_url_data.get("url", "")
            if url.startswith("data:"):
                # Parse data URL: data:mime_type;base64,data
                parts = url.split(",", 1)
                mime_type = header.split(":")[1].split(";")[0]
                agui_content.append(BinaryInputContent(type="binary", mime_type=mime_type, data=parts[1]))
            else:
                agui_content.append(BinaryInputContent(type="binary", mime_type="image/png", url=url))
```

LangChain uses the OpenAI multimodal format (`image_url.url`), while AG-UI uses `BinaryInputContent` with separate `mime_type`, `data`, and `url` fields.

#### 4.4.4 Reasoning Content Resolution

Three functions handle model reasoning/thinking content across different provider formats:

```python
def resolve_reasoning_content(chunk) -> LangGraphReasoning | None:
    content = chunk.content
    if isinstance(content, list) and content and content[0]:
        block = content[0]
        # Anthropic format: { type: "thinking", thinking: "..." }
        if block_type == "thinking" and block.get("thinking"):
            return LangGraphReasoning(text=block["thinking"], type="text", index=block.get("index", 0))
        # LangChain standardized: { type: "reasoning", reasoning: "..." }
        if block_type == "reasoning" and block.get("reasoning"):
            return LangGraphReasoning(text=block["reasoning"], type="text", index=block.get("index", 0))
        # OpenAI Responses API: { type: "reasoning", summary: [{ text: "..." }] }
        if block_type == "reasoning" and block.get("summary"):
            ...
    # OpenAI legacy: additional_kwargs.reasoning.summary
    if hasattr(chunk, "additional_kwargs"):
        reasoning = chunk.additional_kwargs.get("reasoning", {})
        ...
```

This handles four different reasoning formats:
1. **Anthropic extended thinking** (old): `content[0].type == "thinking"` with `thinking` field
2. **LangChain standardized**: `content[0].type == "reasoning"` with `reasoning` field
3. **OpenAI Responses API v1**: `content[0].type == "reasoning"` with `summary[0].text`
4. **OpenAI legacy**: `additional_kwargs.reasoning.summary[0].text`

```python
def resolve_encrypted_reasoning_content(chunk) -> str | None:
    content = chunk.content
    # Anthropic redacted_thinking: { type: "redacted_thinking", data: "..." }
    if content[0].get("type") == "redacted_thinking" and content[0].get("data"):
        return content[0]["data"]
```

Handles Anthropic's redacted thinking blocks (encrypted chain-of-thought that the model produces but clients can't read).

#### 4.4.5 make\_json\_safe() -- Deep Serialization

```python
def make_json_safe(value, _seen=None):
    if _seen is None:
        _seen = set()

    obj_id = id(value)
    if obj_id in _seen:
        return "<recursive>"

    # Primitives -> as-is
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    # Enum -> .value
    if isinstance(value, Enum):
        return make_json_safe(value.value, _seen)

    # Dict -> recurse (exclude "runtime" and "config" keys)
    if isinstance(value, dict):
        _seen.add(obj_id)
        return {
            make_json_safe(k, _seen): make_json_safe(v, _seen)
            for k, v in value.items()
            if k not in ("runtime", "config")
        }

    # Iterables -> list
    if isinstance(value, (list, tuple, set, frozenset)):
        _seen.add(obj_id)
        return [make_json_safe(v, _seen) for v in value]

    # Dataclasses -> dict (excluding runtime/config fields)
    if is_dataclass(value):
        _seen.add(obj_id)
        d = {f.name: getattr(value, f.name) for f in fields(value)
             if f.name not in ("runtime", "config")}
        return make_json_safe(d, _seen)

    # Pydantic models -> model_dump() / dict() / to_dict()
    # Objects with __dict__ -> vars()
    # Last resort -> repr()
```

This function exists because LangGraph injects non-serializable `runtime` and `config` objects into event data (including `_thread.lock` objects). Standard `json.dumps()` fails on these. `make_json_safe()` recursively converts any value to a JSON-serializable form by:
1. Stripping `runtime` and `config` keys (LangGraph-injected, not serializable)
2. Handling circular references via `_seen` set
3. Converting dataclasses, Pydantic models, and arbitrary objects
4. Falling back to `repr()` for truly unconvertible objects

#### 4.4.6 Utility Helpers

```python
def resolve_message_content(content) -> str | None:
    """Extract text from various content formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content:
        return next((c.get("text") for c in content
                     if isinstance(c, dict) and c.get("type") == "text"), None)

def normalize_tool_content(content) -> str:
    """Normalize tool message content to a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get('type') == 'text':
                parts.append(block.get('text', ''))
            else:
                parts.append(json.dumps(block))
        return ''.join(parts)

def flatten_user_content(content) -> str:
    """Flatten multimodal content into plain text for backwards compatibility."""
    # TextInputContent -> text, BinaryInputContent -> "[Binary content: ...]"

def camel_to_snake(name):
    """Convert camelCase to snake_case."""
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

def filter_object_by_schema_keys(obj, schema_keys):
    """Keep only specified keys from a dict."""
    return {k: v for k, v in obj.items() if k in schema_keys}
```

---

## 5. Endpoint and Middleware

### 5.1 endpoint.py -- FastAPI Integration

```python
def add_langgraph_fastapi_endpoint(app: FastAPI, agent: LangGraphAgent, path: str = "/"):
    @app.post(path)
    async def langgraph_agent_endpoint(input_data: RunAgentInput, request: Request):
        accept_header = request.headers.get("accept")
        encoder = EventEncoder(accept=accept_header)

        # Clone the agent for request isolation
        request_agent = agent.clone()

        async def event_generator():
            async for event in request_agent.run(input_data):
                yield encoder.encode(event)

        return StreamingResponse(
            event_generator(),
            media_type=encoder.get_content_type()
        )

    @app.get(f"{path}/health")
    def health():
        return {"status": "ok", "agent": {"name": agent.name}}
```

This helper registers two routes on a FastAPI app:

| Route | Method | Purpose |
|-------|--------|---------|
| `{path}` | POST | Accept `RunAgentInput`, stream AG-UI events via SSE |
| `{path}/health` | GET | Health check returning agent name |

Key implementation details:
- **`agent.clone()`** is called per request. This is critical: `LangGraphAgent` stores per-request state in `self.active_run` and `self.messages_in_process`. Without cloning, concurrent requests would corrupt each other's state.
- **`EventEncoder`** (from `ag_ui.core`) handles SSE formatting. It respects the `Accept` header to determine the content type (`text/event-stream` or `application/x-ndjson`).
- **`RunAgentInput`** is a Pydantic model, so FastAPI automatically parses and validates the request body.

### 5.2 middlewares/state\_streaming.py -- StateStreamingMiddleware

The `StateStreamingMiddleware` enables **predict_state** -- a feature where tool call arguments are streamed to the client as incremental state updates before the tool finishes executing.

```python
@dataclass(frozen=True)
class StateItem:
    state_key: str       # e.g., "recipe"
    tool: str            # e.g., "write_recipe"
    tool_argument: str   # e.g., "draft"
```

A `StateItem` maps a tool call to a state key. When the model calls `write_recipe(draft="...")`, the streaming `draft` argument value is pushed to the client as a `STATE_SNAPSHOT` update for the `recipe` key -- before the tool finishes.

```python
class StateStreamingMiddleware(AgentMiddleware):
    def __init__(self, *items: StateItem):
        self._emit_intermediate_state = [
            {"state_key": i.state_key, "tool": i.tool, "tool_argument": i.tool_argument}
            for i in items
        ]

    def _is_pre_tool_call(self, request: ModelRequest) -> bool:
        msgs = request.messages
        return not (msgs and isinstance(msgs[-1], ToolMessage))
```

The `_is_pre_tool_call()` check prevents duplicate streaming. When the last message is a `ToolMessage`, the model is being called for a follow-up response after a tool executed -- not making a new tool call. Without this guard, predict_state would fire again if the model calls the same tool twice.

```python
    def wrap_model_call(self, request, handler):
        if not self._is_pre_tool_call(request):
            return handler(request)  # Pass through unchanged

        config = _with_intermediate_state(ensure_config(), self._emit_intermediate_state)
        token = var_child_runnable_config.set(config)
        try:
            return handler(request)
        finally:
            var_child_runnable_config.reset(token)
```

The middleware injects `predict_state` metadata into the LangChain runnable config via `var_child_runnable_config` (a `contextvars.ContextVar`). This metadata is then available in `event.metadata["predict_state"]` during streaming, where `_handle_single_event()` in the agent picks it up and emits `PredictState` custom events.

The `try/finally` block ensures the context variable is always reset, even if the handler raises an exception. This prevents predict_state metadata from leaking into subsequent model calls.

**Helper function:**
```python
def _with_intermediate_state(config, emit_intermediate_state):
    metadata = {**config.get("metadata", {}), "predict_state": emit_intermediate_state}
    return {**config, "metadata": metadata}
```

Creates a new config dict with `predict_state` added to the metadata. Does not mutate the original config.

---

## 6. Tests

The test suite covers four areas with `unittest`:

### 6.1 test\_clone.py

Tests that `clone()` correctly handles subclass identity, field copying, and isolation:

| Test | Verifies |
|------|----------|
| `test_clone_returns_same_class` | Subclass identity preserved (`type(self)()`) |
| `test_clone_copies_fields` | name, graph, description, config all copied |
| `test_clone_shallow_copies_config` | Config dict is a new object, not a reference |
| `test_clone_subclass_has_overridden_methods` | Subclass methods work on cloned instance |
| `test_clone_does_not_preserve_subclass_extra_state` | Extra subclass state reverts to defaults (documented limitation) |
| `test_clone_subclass_with_required_extra_param_raises` | Clear `TypeError` when subclass needs more params |
| `test_clone_isolates_mutable_state` | `messages_in_process` is a separate dict |

### 6.2 test\_make\_json\_safe.py

Tests the deep serialization utility against edge cases:

- Primitives, enums, dicts, lists, tuples, sets
- Simple dataclasses
- **Dataclasses with unpicklable objects** (`threading.Lock`) -- verifies fallback from `asdict()` to `__dict__`
- **Circular references** in dicts, lists, and objects -- verifies `<recursive>` sentinel
- **`runtime` and `config` exclusion** -- verifies LangGraph-injected keys are stripped from dicts and dataclasses
- Full round-trip: `json.dumps(make_json_safe(value))` succeeds on problematic inputs

### 6.3 test\_multimodal.py

Tests bidirectional multimodal message conversion:

- Text-only AG-UI to LangChain (string content preserved)
- Multimodal AG-UI to LangChain (URL images, base64 data images)
- LangChain multimodal to AG-UI (URL and data URL parsing)
- `flatten_user_content()` for backwards compatibility
- Helper function unit tests for both conversion directions

### 6.4 test\_state\_streaming\_middleware.py

Comprehensive tests for `StateStreamingMiddleware`:

- **`_is_pre_tool_call` logic**: Empty messages (True), HumanMessage last (True), ToolMessage last (False)
- **`wrap_model_call`**: Injects config when pre-tool-call, passes through when post-tool-call
- **`awrap_model_call`**: Same behavior in async
- **Config injection verification**: Checks `var_child_runnable_config` actually contains `predict_state`
- **Cleanup on exception**: `var_child_runnable_config` is reset even when handler raises
- **Snapshot suppression condition**: Verifies the `suppressed = exiting_node and (mmtc or not state_reliable)` truth table
- **`model_made_tool_call` metadata check**: Only set when tool name matches `predict_state` metadata, not for arbitrary tools

---

## 7. End-to-End Request Lifecycle

### 7.1 New Chat Message (Happy Path)

Trace of a user sending "Create a welcome email template" to a template-building agent:

```
Step 1: HTTP Request
────────────────────
Client sends POST /agent with body:
{
  "thread_id": "thread-abc",
  "run_id": "run-123",
  "messages": [{"id": "msg-1", "role": "user", "content": "Create a welcome email template"}],
  "state": {},
  "tools": [],
  "context": [],
  "forwarded_props": {}
}

Step 2: endpoint.py -- Request Handling
───────────────────────────────────────
add_langgraph_fastapi_endpoint handler:
  input_data = RunAgentInput(**body)         # Pydantic validation
  request_agent = agent.clone()              # Fresh per-request state
  StreamingResponse(event_generator())       # Start SSE stream

Step 3: agent.run(input_data)
─────────────────────────────
  forwarded_props = {} (nothing to convert)
  -> delegates to _handle_stream_events(input_data)

Step 4: _handle_stream_events() -- Initialization
──────────────────────────────────────────────────
  active_run = {
    "id": "run-123",
    "thread_id": "thread-abc",
    "node_name": None,
    "state_reliable": True,
    "model_made_tool_call": False,
    ...
  }
  agent_state = await graph.aget_state(config)  # Read checkpointer (empty for new thread)

Step 5: prepare_stream() -- State Merge
────────────────────────────────────────
  langchain_messages = agui_messages_to_langchain([UserMessage("Create a welcome...")])
  -> [HumanMessage(id="msg-1", content="Create a welcome email template")]

  state = langgraph_default_merge_state(state_input, langchain_messages, input)
  -> {
       "messages": [HumanMessage(...)],  # Only new messages
       "tools": [],
       "ag-ui": {"tools": [], "context": []},
       "copilotkit": {"actions": []}
     }

  stream = graph.astream_events(input=state, version="v2", config=config)
  return {"stream": stream, "state": state, "config": config}

Step 6: Event Emission -- RUN_STARTED
─────────────────────────────────────
  yield RunStartedEvent(type="RUN_STARTED", thread_id="thread-abc", run_id="run-123")
  -> SSE: data: {"type":"RUN_STARTED","threadId":"thread-abc","runId":"run-123"}

Step 7: Main Loop -- Processing LangGraph Events
─────────────────────────────────────────────────
  Event: {event: "on_chain_start", metadata: {langgraph_node: "generate_template"}}
    -> handle_node_change("generate_template")
    -> yield StepStartedEvent(step_name="generate_template")
    -> SSE: data: {"type":"STEP_STARTED","stepName":"generate_template"}

  Event: {event: "on_custom_event", name: "activity_snapshot", data: {...}}
    -> yield CustomEvent(name="activity_snapshot", value={...})

  Event: {event: "on_chat_model_stream", data: {chunk: AIMessageChunk(content="")}}
    -> (no content, skip)

  Event: {event: "on_chat_model_stream", data: {chunk: AIMessageChunk(content="Sure")}}
    -> No message in progress, content present
    -> yield TextMessageStartEvent(role="assistant", message_id="ai-chunk-id")
    -> yield TextMessageContentEvent(message_id="ai-chunk-id", delta="Sure")
    -> SSE: data: {"type":"TEXT_MESSAGE_START",...}
    -> SSE: data: {"type":"TEXT_MESSAGE_CONTENT","delta":"Sure",...}

  Event: {event: "on_chat_model_stream", data: {chunk: AIMessageChunk(content=", I'll")}}
    -> Message in progress, content present
    -> yield TextMessageContentEvent(delta=", I'll")

  ... (more streaming chunks) ...

  Event: {event: "on_chat_model_stream", data: {chunk: {response_metadata: {finish_reason: "end_turn"}}}}
    -> finish_reason set, SKIP (no emission)

  Event: {event: "on_chat_model_end", data: {output: AIMessage(...)}}
    -> Message in progress has ID -> yield TextMessageEndEvent(message_id="ai-chunk-id")
    -> Append output to streamed_messages

  Event: {event: "on_chain_end", data: {output: {template: {...}, version: 1}}}
    -> exiting_node = True, model_made_tool_call = False, state_reliable = True
    -> NOT suppressed
    -> yield StateSnapshotEvent(snapshot={template: {...}, version: 1})

Step 8: Post-Stream Finalization
────────────────────────────────
  state = await graph.aget_state(config)  # Read final checkpoint
  -> {template: {...}, version: 1, messages: [...]}

  yield StateSnapshotEvent(snapshot=get_state_snapshot(state.values))
  yield MessagesSnapshotEvent(messages=langchain_messages_to_agui(state.values["messages"]))
  yield StepFinishedEvent(step_name="generate_template")
  yield RunFinishedEvent(thread_id="thread-abc", run_id="run-123")
  active_run = None

Step 9: SSE Stream Closes
─────────────────────────
  StreamingResponse ends, connection closes.
```

### 7.2 Reconnection / Time-Travel

When a user edits a previous message (time-travel):

```
Step 1: Client sends messages where the last user message ID exists in the checkpoint
        but the checkpoint has MORE messages after it (e.g., AI responses to the original).

Step 2: prepare_stream() detects:
        len(agent_state.values["messages"]) > len(non_system_messages)
        AND incoming message IDs are a subset of checkpoint IDs
        BUT the last HumanMessage ID is in the checkpoint
        -> NOT a continuation, this is time-travel

Step 3: prepare_regenerate_stream():
        a. get_checkpoint_before_message(last_user_message.id)
           -> Walks aget_state_history() to find snapshot at idx-1
        b. graph.aupdate_state(time_travel_checkpoint.config, values, as_node="__start__")
           -> Forks the checkpoint
        c. Starts a new stream from the forked checkpoint with the edited message

Step 4: Normal event loop continues from the fork point.
        The graph re-runs from the edited message, producing new results.
```

### 7.3 Interrupt and Resume

When a graph has an active interrupt (e.g., human-in-the-loop):

```
Step 1: First request -- graph runs and hits an interrupt
        The stream ends naturally, and the final state includes the interrupt.
        -> yield CustomEvent(name="on_interrupt", value=interrupt_value)
        -> yield RunFinishedEvent(...)

Step 2: Second request -- client sends the same thread with no resume
        prepare_stream() detects:
          has_active_interrupts = True
          resume_input = None
        -> Returns pre-built events without starting a stream:
           [RunStartedEvent, CustomEvent("on_interrupt", ...), RunFinishedEvent]

Step 3: Third request -- client sends resume value in forwarded_props
        prepare_stream() detects:
          resume_input = forwarded_props["command"]["resume"]
        -> stream_input = Command(resume=resume_input)
        -> graph.astream_events(input=Command(resume=...), ...)
        -> Normal event loop continues from the interrupt point
```

---

*Document generated from `ag-ui-langgraph` v0.0.29 source at [github.com/ag-ui-protocol/ag-ui](https://github.com/ag-ui-protocol/ag-ui), commit on `integrations/langgraph/python/`.*
