# Template Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an email template creation/modification agent using `ag-ui-langgraph`, alongside the existing segment agent, with Redis Pub/Sub streaming and LangGraph checkpointer-based reconnection.

**Architecture:** `LangGraphAgent.run()` auto-generates AG-UI events from graph execution. An `EventAdapter` bridges these events to SSE strings, translating custom events and filtering state snapshots. The SSE strings feed into the existing `agent_runner` → Redis Pub/Sub pipeline. Reconnection reads from LangGraph checkpointer (single source of truth) then bridges to live Pub/Sub.

**Tech Stack:** ag-ui-langgraph, LangGraph, FastAPI, Redis Pub/Sub, CopilotKit, Next.js, Tailwind CSS v4

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `pyproject.toml` | Modify | Add ag-ui-langgraph dependency |
| `src/stream_reconnection_demo/schemas/template.py` | Create | EmailTemplate + TemplateSection Pydantic models |
| `src/stream_reconnection_demo/agent/template/__init__.py` | Create | Package init |
| `src/stream_reconnection_demo/agent/template/state.py` | Create | TemplateAgentState + TemplateOutput TypedDicts |
| `src/stream_reconnection_demo/agent/template/graph.py` | Create | LangGraph with generate/modify nodes, conditional routing, custom events |
| `src/stream_reconnection_demo/core/event_adapter.py` | Create | Bridges LangGraphAgent.run() → SSE strings |
| `src/stream_reconnection_demo/agent/template/routes.py` | Create | POST endpoint with chat/connect/duplicate flows |
| `src/stream_reconnection_demo/main.py` | Modify | Add template graph, LangGraphAgent, router in lifespan |
| `frontend-next/lib/types.ts` | Modify | Add EmailTemplate + TemplateSection interfaces |
| `frontend-next/app/api/copilotkit/template/route.ts` | Create | CopilotKit proxy with connect interceptor |
| `frontend-next/components/TemplatePreview.tsx` | Create | Sandboxed iframe HTML preview |
| `frontend-next/components/TemplateEditor.tsx` | Create | Template metadata bar + preview wrapper |
| `frontend-next/app/template/page.tsx` | Create | Template agent page with CopilotKit |
| `frontend-next/components/Nav.tsx` | Modify | Add template tab with active state |
| `frontend-next/app/page.tsx` | Modify | Card grid home page |

---

### Task 1: Add ag-ui-langgraph dependency

**Files:**
- Modify: `pyproject.toml:6-15`

- [ ] **Step 1: Add dependency to pyproject.toml**

In the `dependencies` list, add `ag-ui-langgraph`:

```toml
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

- [ ] **Step 2: Install the dependency**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv sync`

Expected: Resolves and installs `ag-ui-langgraph` and its transitive dependencies. No errors.

- [ ] **Step 3: Verify import works**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from ag_ui_langgraph import LangGraphAgent; print('OK')"`

Expected: Prints `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add ag-ui-langgraph dependency"
```

---

### Task 2: Create EmailTemplate schema

**Files:**
- Create: `src/stream_reconnection_demo/schemas/template.py`

- [ ] **Step 1: Create the Pydantic models**

Create `src/stream_reconnection_demo/schemas/template.py`:

```python
from pydantic import BaseModel


class TemplateSection(BaseModel):
    id: str
    type: str  # header, body, footer, cta, image
    content: str
    styles: dict[str, str] = {}


class EmailTemplate(BaseModel):
    html: str = ""
    css: str = ""
    subject: str = ""
    preview_text: str = ""
    sections: list[TemplateSection] = []
    version: int = 1
```

- [ ] **Step 2: Verify import**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.schemas.template import EmailTemplate, TemplateSection; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/schemas/template.py
git commit -m "feat: add EmailTemplate and TemplateSection Pydantic models"
```

---

### Task 3: Create template agent state

**Files:**
- Create: `src/stream_reconnection_demo/agent/template/__init__.py`
- Create: `src/stream_reconnection_demo/agent/template/state.py`

- [ ] **Step 1: Create package init**

Create `src/stream_reconnection_demo/agent/template/__init__.py` as an empty file.

- [ ] **Step 2: Create state TypedDicts**

Create `src/stream_reconnection_demo/agent/template/state.py`:

```python
from operator import add
from typing import Annotated, TypedDict


class TemplateAgentState(TypedDict):
    messages: Annotated[list, add]
    template: dict | None
    error: str | None
    version: int


class TemplateOutput(TypedDict):
    """Output schema — limits STATE_SNAPSHOT to template field only."""
    template: dict | None
```

- [ ] **Step 3: Verify import**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.agent.template.state import TemplateAgentState, TemplateOutput; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/__init__.py src/stream_reconnection_demo/agent/template/state.py
git commit -m "feat: add TemplateAgentState and TemplateOutput TypedDicts"
```

---

### Task 4: Create template agent graph

**Files:**
- Create: `src/stream_reconnection_demo/agent/template/graph.py`

- [ ] **Step 1: Create the graph module**

Create `src/stream_reconnection_demo/agent/template/graph.py`:

```python
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from stream_reconnection_demo.agent.template.state import (
    TemplateAgentState,
    TemplateOutput,
)
from stream_reconnection_demo.schemas.template import EmailTemplate

GENERATE_SYSTEM_PROMPT = """\
You are an expert email template designer. Given a user's description, \
generate a professional HTML email template.

## Output Requirements

- A clear, descriptive subject line.
- A short preview text (the snippet shown in email clients).
- Fully self-contained HTML with **inline CSS** (email clients strip \
<style> blocks).
- Use a 600px centered container for maximum compatibility.
- Include sections such as header, body, CTA (call-to-action), and footer.
- Each section must have a unique ``id`` (e.g. "s1", "s2"), a ``type`` \
(header | body | cta | footer | image), and its HTML ``content``.
- Keep the design responsive using percentage-based widths inside the \
600px container.
- Use web-safe fonts (Arial, Helvetica, Georgia, etc.).
"""

MODIFY_SYSTEM_PROMPT = """\
You are an expert email template designer. The user has an existing \
template and wants to modify it.

## Current Template

Subject: {subject}
Sections: {sections}

Full HTML:
{html}

## Instructions

Apply the user's requested changes to the template. Preserve any \
sections not mentioned. Return the complete updated template with all \
sections.
"""


def _build_generate_node(llm: ChatAnthropic):
    structured_llm = llm.with_structured_output(EmailTemplate)

    async def generate_template(
        state: TemplateAgentState, config: RunnableConfig
    ) -> dict:
        try:
            query = ""
            for msg in reversed(state["messages"]):
                if hasattr(msg, "content"):
                    query = msg.content
                    break
                elif isinstance(msg, dict) and msg.get("role") == "user":
                    query = msg.get("content", "")
                    break

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Generating template",
                    "progress": 0.1,
                    "details": "Starting LLM generation...",
                },
                config=config,
            )

            messages = [
                SystemMessage(content=GENERATE_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ]
            result = await structured_llm.ainvoke(messages, config=config)

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Template generated",
                    "progress": 1.0,
                    "details": f"Created: {result.subject}",
                },
                config=config,
            )

            return {
                "template": result.model_dump(),
                "error": None,
                "version": 1,
            }
        except Exception as e:
            return {"template": None, "error": str(e)}

    return generate_template


def _build_modify_node(llm: ChatAnthropic):
    structured_llm = llm.with_structured_output(EmailTemplate)

    async def modify_template(
        state: TemplateAgentState, config: RunnableConfig
    ) -> dict:
        try:
            query = ""
            for msg in reversed(state["messages"]):
                if hasattr(msg, "content"):
                    query = msg.content
                    break
                elif isinstance(msg, dict) and msg.get("role") == "user":
                    query = msg.get("content", "")
                    break

            existing = state.get("template") or {}
            sections_summary = json.dumps(
                [
                    {"id": s.get("id"), "type": s.get("type")}
                    for s in existing.get("sections", [])
                ]
            )

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Modifying template",
                    "progress": 0.1,
                    "details": "Applying changes...",
                },
                config=config,
            )

            system_content = MODIFY_SYSTEM_PROMPT.format(
                subject=existing.get("subject", ""),
                sections=sections_summary,
                html=existing.get("html", ""),
            )

            messages = [
                SystemMessage(content=system_content),
                HumanMessage(content=query),
            ]
            result = await structured_llm.ainvoke(messages, config=config)
            current_version = state.get("version", 0)

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Template updated",
                    "progress": 1.0,
                    "details": f"Updated: {result.subject}",
                },
                config=config,
            )

            return {
                "template": result.model_dump(),
                "error": None,
                "version": current_version + 1,
            }
        except Exception as e:
            return {"template": state.get("template"), "error": str(e)}

    return modify_template


def _route_by_state(state: TemplateAgentState) -> str:
    """Route to generate or modify based on whether a template exists."""
    if state.get("template") is None:
        return "generate_template"
    return "modify_template"


def build_template_graph(checkpointer=None, model="claude-sonnet-4-20250514"):
    """Build and compile the template generation/modification graph."""
    llm = ChatAnthropic(model=model)

    graph = StateGraph(TemplateAgentState, output=TemplateOutput)
    graph.add_node("generate_template", _build_generate_node(llm))
    graph.add_node("modify_template", _build_modify_node(llm))
    graph.add_conditional_edges(START, _route_by_state)
    graph.add_edge("generate_template", END)
    graph.add_edge("modify_template", END)

    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 2: Verify import and graph builds**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.agent.template.graph import build_template_graph; g = build_template_graph(); print('Graph nodes:', list(g.nodes.keys()))"`

Expected: Prints node names including `generate_template` and `modify_template`.

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/graph.py
git commit -m "feat: add template agent graph with generate/modify nodes"
```

---

### Task 5: Create EventAdapter

**Files:**
- Create: `src/stream_reconnection_demo/core/event_adapter.py`

- [ ] **Step 1: Create the EventAdapter module**

Create `src/stream_reconnection_demo/core/event_adapter.py`:

```python
"""Bridges LangGraphAgent.run() output to SSE strings.

Translates custom events into proper AG-UI event types, filters
intermediate STATE_SNAPSHOT events, and encodes everything via
EventEncoder for the agent_runner pipeline.
"""

from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator

from ag_ui.core import (
    ActivitySnapshotEvent,
    EventType,
    RunAgentInput,
    StateDeltaEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder
from ag_ui_langgraph import LangGraphAgent

logger = logging.getLogger(__name__)


class EventAdapter:
    """Adapts LangGraphAgent event objects to SSE strings.

    Yields ``str`` values in the same format as ``run_segment_pipeline()``
    so the existing ``agent_runner`` can consume them without changes.
    """

    def __init__(self) -> None:
        self._encoder = EventEncoder()

    async def stream_events(
        self,
        agent: LangGraphAgent,
        input_data: RunAgentInput,
        *,
        state_snapshot_key: str = "template",
    ) -> AsyncIterator[str]:
        """Run the agent and yield SSE-encoded event strings.

        Parameters
        ----------
        agent:
            The LangGraphAgent to execute.
        input_data:
            AG-UI input payload (thread_id, run_id, messages, state, etc.).
        state_snapshot_key:
            The key in STATE_SNAPSHOT to check. Intermediate snapshots
            where this key is ``None`` are suppressed.
        """
        async for event_obj in agent.run(input_data):
            # --- Custom event translation ---------------------------------
            if event_obj.type == EventType.CUSTOM:
                async for translated in self._translate_custom(event_obj):
                    yield self._encoder.encode(translated)
                continue

            # --- STATE_SNAPSHOT filtering ----------------------------------
            # Suppress intermediate snapshots where the output key is None
            if event_obj.type == EventType.STATE_SNAPSHOT:
                snapshot = getattr(event_obj, "snapshot", None) or {}
                if isinstance(snapshot, dict) and snapshot.get(state_snapshot_key) is None:
                    continue

            # --- Inject empty state reset after RUN_STARTED ---------------
            if event_obj.type == EventType.RUN_STARTED:
                yield self._encoder.encode(event_obj)
                yield self._encoder.encode(
                    StateSnapshotEvent(
                        type=EventType.STATE_SNAPSHOT,
                        snapshot={},
                    )
                )
                continue

            yield self._encoder.encode(event_obj)

    async def _translate_custom(self, event_obj):
        """Translate CUSTOM events to proper AG-UI event types."""
        name = getattr(event_obj, "name", "")
        data = getattr(event_obj, "value", {})

        if name == "activity_snapshot":
            yield ActivitySnapshotEvent(
                type=EventType.ACTIVITY_SNAPSHOT,
                message_id=str(uuid.uuid4()),
                activity_type="processing",
                content=data,
            )

        elif name == "state_delta":
            ops = data.get("ops", []) if isinstance(data, dict) else []
            if ops:
                yield StateDeltaEvent(
                    type=EventType.STATE_DELTA,
                    delta=ops,
                )

        # Unknown custom events are silently dropped (not re-emitted as CUSTOM)
```

- [ ] **Step 2: Verify import**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.core.event_adapter import EventAdapter; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/core/event_adapter.py
git commit -m "feat: add EventAdapter bridging LangGraphAgent to SSE strings"
```

---

### Task 6: Create template agent routes

**Files:**
- Create: `src/stream_reconnection_demo/agent/template/routes.py`

- [ ] **Step 1: Create the routes module**

Create `src/stream_reconnection_demo/agent/template/routes.py`:

```python
"""Template agent endpoint — ag-ui-langgraph + Redis Pub/Sub.

Uses LangGraphAgent for automatic AG-UI event generation.
Checkpointer is the single source of truth for catch-up.
Redis Pub/Sub for live event streaming only (no List).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from ag_ui.core import RunAgentInput, UserMessage
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stream_reconnection_demo.core.event_adapter import EventAdapter
from stream_reconnection_demo.core.events import (
    EventEmitter,
    extract_user_query,
    get_field,
)
from stream_reconnection_demo.core.pubsub import STREAM_END, STREAM_ERROR

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)


@router.post("/template")
async def handle_template(request: Request):
    body = await request.json()

    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    messages = body.get("messages", [])
    query = extract_user_query(messages)
    frontend_state = body.get("state")

    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    template_graph = request.app.state.template_graph
    template_agent = request.app.state.template_agent
    pubsub = request.app.state.pubsub

    logger.info(
        "Template request: thread=%s type=%s query=%s",
        thread_id,
        request_type,
        query[:50] if query else "(empty)",
    )

    if request_type == "connect":
        return await _handle_connect(pubsub, template_graph, thread_id, run_id)

    return await _handle_chat(
        pubsub,
        template_graph,
        template_agent,
        thread_id,
        run_id,
        query,
        frontend_state,
    )


@router.get("/template/state/{thread_id}")
async def get_template_state(thread_id: str, request: Request):
    """Return current template state from checkpointer for a given thread."""
    template_graph = request.app.state.template_graph
    try:
        checkpoint_state = await template_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if checkpoint_state and checkpoint_state.values:
            template = checkpoint_state.values.get("template")
            if template:
                return {"template": template}
    except Exception:
        logger.warning("Failed to read state for thread %s", thread_id)
    return {"template": None}


async def _handle_chat(
    pubsub,
    template_graph,
    template_agent,
    thread_id: str,
    run_id: str,
    query: str,
    frontend_state: dict | None,
):
    """Handle Chat — start new run via LangGraphAgent + EventAdapter."""

    if not query.strip():
        return await _handle_connect(pubsub, template_graph, thread_id, run_id)

    # Duplicate query detection via checkpointer
    try:
        checkpoint_state = await template_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if checkpoint_state and checkpoint_state.values:
            existing_messages = checkpoint_state.values.get("messages", [])
            last_human = None
            for msg in reversed(existing_messages):
                if hasattr(msg, "type") and msg.type == "human":
                    last_human = msg.content
                    break
            if last_human == query:
                logger.info(
                    "Template chat: query already processed for thread %s",
                    thread_id,
                )

                async def _already_done():
                    yield emitter.emit_run_started(thread_id, run_id)
                    template = checkpoint_state.values.get("template")
                    if template is not None:
                        yield emitter.emit_state_snapshot(template)
                    yield emitter.emit_run_finished(thread_id, run_id)

                return StreamingResponse(
                    _already_done(), media_type=emitter.content_type
                )
    except Exception:
        logger.warning("Checkpointer check failed for thread %s", thread_id)

    logger.info("Template chat: new run %s for thread %s", run_id, thread_id)

    try:
        await pubsub.start_run(thread_id, run_id)
    except Exception:
        logger.warning("Failed to register run in Redis")

    # Build RunAgentInput for LangGraphAgent
    existing_template = frontend_state
    if existing_template is None:
        try:
            cp = await template_graph.aget_state(
                {"configurable": {"thread_id": thread_id}}
            )
            if cp and cp.values:
                existing_template = cp.values.get("template")
        except Exception:
            pass

    input_data = RunAgentInput(
        thread_id=thread_id,
        run_id=run_id,
        messages=[UserMessage(id=str(uuid.uuid4()), role="user", content=query)],
        state={"template": existing_template, "version": existing_template.get("version", 0) if existing_template else 0},
        tools=[],
        context=[],
        forwarded_props={},
    )

    adapter = EventAdapter()
    event_stream = adapter.stream_events(
        template_agent, input_data, state_snapshot_key="template"
    )

    from stream_reconnection_demo.core.agent_runner import (
        start_agent_task_pubsub_only,
    )

    start_agent_task_pubsub_only(
        pubsub, template_graph, thread_id, run_id, event_stream
    )

    await asyncio.sleep(0.1)

    async def live_stream():
        try:
            async for event_sse in pubsub.subscribe_and_stream(
                thread_id, run_id, last_seq=0
            ):
                yield event_sse
        except Exception:
            logger.exception("Template live stream failed for run %s", run_id)
            yield emitter.emit_run_error("Stream failed")

    return StreamingResponse(live_stream(), media_type=emitter.content_type)


async def _handle_connect(pubsub, template_graph, thread_id: str, run_id: str):
    """Handle Connect — catch-up from checkpointer, then bridge to live Pub/Sub."""

    active_run_id = None
    try:
        active_run_id = await pubsub.get_active_run(thread_id)
    except Exception:
        logger.warning("Failed to check active run for thread %s", thread_id)

    if active_run_id:
        logger.info(
            "Template connect: active run %s, catching up from checkpointer",
            active_run_id,
        )

        async def reconnect_stream():
            channel_key = pubsub._channel_key(thread_id, active_run_id)
            ps = pubsub._redis.pubsub()
            await ps.subscribe(channel_key)

            try:
                # Read checkpointer state for catch-up
                try:
                    checkpoint_state = await template_graph.aget_state(
                        {"configurable": {"thread_id": thread_id}}
                    )
                except Exception:
                    checkpoint_state = None

                # Emit synthetic catch-up events
                async for event in _emit_synthetic_catchup(
                    checkpoint_state.values if checkpoint_state and checkpoint_state.values else {},
                    thread_id,
                    run_id,
                ):
                    yield event

                # Yield live events from Pub/Sub
                while True:
                    message = await ps.get_message(
                        ignore_subscribe_messages=True, timeout=5.0
                    )
                    if message is None:
                        status = await pubsub.get_run_status(
                            thread_id, active_run_id
                        )
                        if status in ("completed", "error"):
                            try:
                                final_state = await template_graph.aget_state(
                                    {"configurable": {"thread_id": thread_id}}
                                )
                                if final_state and final_state.values:
                                    template = final_state.values.get("template")
                                    if template:
                                        yield emitter.emit_state_snapshot(template)
                            except Exception:
                                pass
                            yield emitter.emit_run_finished(thread_id, run_id)
                            return
                        continue

                    if message["type"] != "message":
                        continue

                    try:
                        parsed = json.loads(message["data"])
                        event_data = parsed.get("event", "")
                    except (ValueError, TypeError):
                        continue

                    if event_data in (STREAM_END, STREAM_ERROR):
                        try:
                            final_state = await template_graph.aget_state(
                                {"configurable": {"thread_id": thread_id}}
                            )
                            if final_state and final_state.values:
                                template = final_state.values.get("template")
                                if template:
                                    yield emitter.emit_state_snapshot(template)
                        except Exception:
                            pass
                        yield emitter.emit_run_finished(thread_id, run_id)
                        return

                    yield event_data
            finally:
                await ps.unsubscribe(channel_key)
                await ps.aclose()

        return StreamingResponse(
            reconnect_stream(), media_type=emitter.content_type
        )

    # No active run — check checkpointer for completed state
    try:
        checkpoint_state = await template_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        checkpoint_state = None

    if checkpoint_state and checkpoint_state.values:
        logger.info(
            "Template connect: completed state from checkpointer for thread %s",
            thread_id,
        )

        async def completed_stream():
            async for event in _emit_synthetic_catchup(
                checkpoint_state.values, thread_id, run_id
            ):
                yield event
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            completed_stream(), media_type=emitter.content_type
        )

    # Nothing found
    logger.info("Template connect: no state for thread %s", thread_id)

    async def empty_stream():
        yield emitter.emit_run_started(thread_id, run_id)
        yield emitter.emit_run_finished(thread_id, run_id)

    return StreamingResponse(empty_stream(), media_type=emitter.content_type)


async def _emit_synthetic_catchup(state: dict, thread_id: str, run_id: str):
    """Emit synthetic AG-UI events from checkpointer state for catch-up."""
    yield emitter.emit_run_started(thread_id, run_id)

    # Restore chat history
    messages = state.get("messages", [])
    if messages:
        agui_msgs = emitter.langchain_messages_to_agui(messages)
        if agui_msgs:
            yield emitter.emit_messages_snapshot(agui_msgs)

    # Emit template state snapshot
    template = state.get("template")
    if template:
        yield emitter.emit_state_snapshot(template)
```

- [ ] **Step 2: Verify import**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run python -c "from stream_reconnection_demo.agent.template.routes import router; print('Routes:', [r.path for r in router.routes])"`

Expected: Shows `/template` and `/template/state/{thread_id}` routes.

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/routes.py
git commit -m "feat: add template agent routes with chat/connect/duplicate flows"
```

---

### Task 7: Wire template agent into main.py

**Files:**
- Modify: `src/stream_reconnection_demo/main.py`

- [ ] **Step 1: Add imports**

Add these imports at the top of `main.py`, after the existing imports:

```python
from ag_ui_langgraph import LangGraphAgent
from stream_reconnection_demo.agent.template.graph import build_template_graph
from stream_reconnection_demo.agent.template.routes import router as template_router
```

- [ ] **Step 2: Add template graph + agent in lifespan**

In the `lifespan()` function, after the stateful segment graph setup (after `logger.info("Stateful segment graph ready")`), add:

```python
    # Build template agent graph with its own checkpointer
    template_checkpointer = MemorySaver()
    template_graph = build_template_graph(checkpointer=template_checkpointer)
    app.state.template_graph = template_graph
    app.state.template_agent = LangGraphAgent(name="template", graph=template_graph)
    logger.info("Template agent ready")
```

- [ ] **Step 3: Register template router**

After `app.include_router(stateful_segment_router)`, add:

```python
app.include_router(template_router)
```

- [ ] **Step 4: Verify the app starts**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && timeout 5 uv run python -c "from stream_reconnection_demo.main import app; print('App routes:', [r.path for r in app.routes])" 2>&1 || true`

Expected: Shows routes including `/api/v1/template` and `/api/v1/template/state/{thread_id}`.

- [ ] **Step 5: Commit**

```bash
git add src/stream_reconnection_demo/main.py
git commit -m "feat: wire template agent into FastAPI app lifespan"
```

---

### Task 8: Add frontend TypeScript types

**Files:**
- Modify: `frontend-next/lib/types.ts`

- [ ] **Step 1: Add EmailTemplate types**

Append to the end of `frontend-next/lib/types.ts`:

```typescript
export interface TemplateSection {
  id: string;
  type: string;
  content: string;
  styles?: Record<string, string>;
}

export interface EmailTemplate {
  html: string;
  css: string;
  subject: string;
  preview_text: string;
  sections: TemplateSection[];
  version: number;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/lib/types.ts
git commit -m "feat: add EmailTemplate TypeScript types"
```

---

### Task 9: Create CopilotKit API route for template

**Files:**
- Create: `frontend-next/app/api/copilotkit/template/route.ts`

- [ ] **Step 1: Create the API route**

Create `frontend-next/app/api/copilotkit/template/route.ts`:

```typescript
import {
  CopilotRuntime,
  EmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

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

  // Intercept agent/connect for reconnection
  if (body.method === "agent/connect") {
    const threadId = body.body?.threadId ?? body.params?.threadId;
    const runId = body.body?.runId ?? crypto.randomUUID();

    const backendResp = await fetch(`${BACKEND_URL}/api/v1/template`, {
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
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  }

  const newReq = new Request(req.url, {
    method: req.method,
    headers: req.headers,
    body: JSON.stringify(body),
  });

  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new EmptyAdapter(),
    endpoint: "/api/copilotkit/template",
  });
  return handleRequest(newReq);
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/app/api/copilotkit/template/route.ts
git commit -m "feat: add CopilotKit proxy route for template agent"
```

---

### Task 10: Create TemplatePreview component

**Files:**
- Create: `frontend-next/components/TemplatePreview.tsx`

- [ ] **Step 1: Create the component**

Create `frontend-next/components/TemplatePreview.tsx`:

```tsx
"use client";

import { useRef, useEffect } from "react";

interface TemplatePreviewProps {
  html: string;
  css: string;
  editable?: boolean;
  onHtmlChange?: (html: string) => void;
}

export function TemplatePreview({
  html,
  css,
  editable = false,
  onHtmlChange,
}: TemplatePreviewProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const userEditHtml = useRef<string | null>(null);
  const onHtmlChangeRef = useRef(onHtmlChange);
  onHtmlChangeRef.current = onHtmlChange;

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const doc = iframe.contentDocument;
    if (!doc) return;

    // Skip rewrite when the html prop is just feedback from a user edit
    if (userEditHtml.current !== null && userEditHtml.current === html) {
      return;
    }
    userEditHtml.current = null;

    doc.open();
    doc.write(
      `<!DOCTYPE html><html><head><style>${css || ""}</style></head>` +
        `<body style="margin:0;padding:20px;background:#f5f5f5;">` +
        `${html || '<p style="text-align:center;color:#999;padding:40px;">Preview will appear here</p>'}` +
        `</body></html>`,
    );
    doc.close();

    if (editable) {
      doc.designMode = "on";
      doc.addEventListener("input", () => {
        if (!doc.body) return;
        const newHtml = doc.body.innerHTML;
        userEditHtml.current = newHtml;
        onHtmlChangeRef.current?.(newHtml);
      });
    }
  }, [html, css, editable]);

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
        <span className="text-xs font-medium text-gray-500">Preview</span>
        {editable && (
          <span className="text-xs text-blue-500">Click to edit</span>
        )}
      </div>
      <iframe
        ref={iframeRef}
        className="flex-1 w-full bg-white"
        sandbox="allow-same-origin"
        title="Template Preview"
      />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/TemplatePreview.tsx
git commit -m "feat: add TemplatePreview component with iframe rendering"
```

---

### Task 11: Create TemplateEditor component

**Files:**
- Create: `frontend-next/components/TemplateEditor.tsx`

- [ ] **Step 1: Create the component**

Create `frontend-next/components/TemplateEditor.tsx`:

```tsx
"use client";

import type { EmailTemplate } from "@/lib/types";
import { TemplatePreview } from "./TemplatePreview";

interface TemplateEditorProps {
  template: EmailTemplate;
  onHtmlChange?: (html: string) => void;
}

export function TemplateEditor({ template, onHtmlChange }: TemplateEditorProps) {
  return (
    <div className="flex flex-col h-full">
      {/* Metadata bar */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 truncate">
          {template.subject || "Untitled"}
        </h3>
        {template.preview_text && (
          <span className="text-xs text-gray-500 truncate hidden sm:inline">
            {template.preview_text}
          </span>
        )}
        <span className="text-xs text-gray-400 ml-auto shrink-0">
          v{template.version}
        </span>
      </div>

      {/* Editable preview */}
      <div className="flex-1 min-h-0">
        <TemplatePreview
          html={template.html}
          css={template.css}
          editable
          onHtmlChange={onHtmlChange}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/TemplateEditor.tsx
git commit -m "feat: add TemplateEditor component with metadata bar"
```

---

### Task 12: Create template page

**Files:**
- Create: `frontend-next/app/template/page.tsx`

- [ ] **Step 1: Create the page**

Create `frontend-next/app/template/page.tsx`:

```tsx
"use client";

import { Suspense } from "react";
import {
  CopilotKit,
  useCoAgentStateRender,
  useCoAgent,
} from "@copilotkit/react-core";
import {
  CopilotSidebar,
  RenderMessageProps,
  AssistantMessage as DefaultAssistantMessage,
  UserMessage as DefaultUserMessage,
  ImageRenderer as DefaultImageRenderer,
} from "@copilotkit/react-ui";
import { Nav } from "@/components/Nav";
import { TemplateEditor } from "@/components/TemplateEditor";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { useAgentThread } from "@/hooks/useAgentThread";
import type { EmailTemplate } from "@/lib/types";

function CustomRenderMessage({
  message,
  messages,
  inProgress,
  index,
  isCurrentMessage,
  AssistantMessage = DefaultAssistantMessage,
  UserMessage = DefaultUserMessage,
  ImageRenderer = DefaultImageRenderer,
}: RenderMessageProps) {
  if (message.role === "reasoning" || message.role === "activity") {
    if (!inProgress) return null;
    const fromOldTurn = messages
      .slice(index + 1)
      .some((m) => m.role === "assistant" && m.content);
    if (fromOldTurn) return null;

    if (message.role === "reasoning") {
      return <ReasoningPanel reasoning={message.content} defaultOpen />;
    }
    return (
      <ActivityIndicator
        activityType={(message as any).activityType ?? "processing"}
        content={message.content as any}
      />
    );
  }

  if (message.role === "user") {
    return (
      <UserMessage
        key={index}
        rawData={message}
        message={message}
        ImageRenderer={ImageRenderer}
      />
    );
  }

  if (message.role === "assistant") {
    return (
      <AssistantMessage
        key={index}
        rawData={message}
        message={message}
        isLoading={inProgress && isCurrentMessage && !message.content}
        isGenerating={inProgress && isCurrentMessage && !!message.content}
        isCurrentMessage={isCurrentMessage}
      />
    );
  }

  return null;
}

function TemplatePageContent() {
  useCoAgentStateRender({
    name: "default",
    render: ({ state }) =>
      state?.subject ? (
        <div className="my-2 p-2 bg-green-50 dark:bg-green-900/20 rounded text-xs text-green-700 dark:text-green-300">
          Template updated: {state.subject}
        </div>
      ) : null,
  });

  const { state: template, setState: setTemplate } =
    useCoAgent<EmailTemplate>({ name: "default" });

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 overflow-hidden">
        {template?.subject ? (
          <TemplateEditor
            template={template}
            onHtmlChange={(html) => setTemplate({ ...template, html })}
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-gray-400">
              Describe your email template in the sidebar to get started.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

function TemplatePageInner() {
  const { threadId, ready } = useAgentThread();

  return (
    <>
      {ready ? (
        <CopilotKit
          key={threadId}
          runtimeUrl="/api/copilotkit/template"
          threadId={threadId}
        >
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are an email template design assistant. Help the user create and modify professional HTML email templates."
            labels={{
              title: "Template Creator",
              initial:
                'Describe the email template you want to create.\n\nTry: **"A welcome email for new SaaS users with a hero image and CTA button"**',
            }}
          >
            <TemplatePageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function TemplatePage() {
  return (
    <Suspense>
      <TemplatePageInner />
    </Suspense>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/app/template/page.tsx
git commit -m "feat: add template agent page with CopilotKit integration"
```

---

### Task 13: Update Nav component with active tabs

**Files:**
- Modify: `frontend-next/components/Nav.tsx`

- [ ] **Step 1: Replace the Nav component**

Replace the entire content of `frontend-next/components/Nav.tsx` with:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function Nav() {
  const pathname = usePathname();

  const tabs = [
    { href: "/segment", label: "Segment Builder" },
    { href: "/template", label: "Template Builder" },
  ];

  return (
    <header className="border-b border-gray-200 dark:border-gray-700 px-6 py-3 flex items-center justify-between">
      <Link href="/" className="text-lg font-semibold">
        Stream Reconnection Demo
      </Link>
      <nav className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
        {tabs.map((tab) => {
          const isActive = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                isActive
                  ? "bg-white dark:bg-gray-700 shadow-sm"
                  : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/Nav.tsx
git commit -m "feat: update Nav with active tabs for segment and template"
```

---

### Task 14: Update home page with card grid

**Files:**
- Modify: `frontend-next/app/page.tsx`

- [ ] **Step 1: Replace the home page**

Replace the entire content of `frontend-next/app/page.tsx` with:

```tsx
import Link from "next/link";

const agents = [
  {
    href: "/segment",
    title: "Segment Builder",
    description:
      "Build audience segments with an 8-step AI pipeline. Features stream reconnection with Redis Pub/Sub event persistence.",
  },
  {
    href: "/template",
    title: "Template Builder",
    description:
      "Create and modify email templates with AI. Uses ag-ui-langgraph for automatic AG-UI event generation.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
      <div className="max-w-3xl w-full px-6 py-16">
        <h1 className="text-2xl font-bold text-center mb-2">
          Stream Reconnection Demo
        </h1>
        <p className="text-sm text-gray-500 text-center mb-10">
          Choose an agent to get started
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {agents.map((agent) => (
            <Link
              key={agent.href}
              href={agent.href}
              className="block p-6 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 hover:border-blue-400 dark:hover:border-blue-600 hover:shadow-md transition-all"
            >
              <h2 className="text-lg font-semibold mb-2">{agent.title}</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {agent.description}
              </p>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/app/page.tsx
git commit -m "feat: replace redirect with card grid home page"
```

---

### Task 15: End-to-end verification

- [ ] **Step 1: Install backend dependencies**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv sync`

Expected: No errors.

- [ ] **Step 2: Install frontend dependencies**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend-next && npm install`

Expected: No errors.

- [ ] **Step 3: Start Redis**

Ensure Redis is running at `localhost:6379`.

Run: `redis-cli ping`

Expected: `PONG`

- [ ] **Step 4: Start backend**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && uv run uvicorn stream_reconnection_demo.main:app --host 0.0.0.0 --port 8000 --reload`

Expected: App starts, logs show "Template agent ready" alongside segment graph messages.

- [ ] **Step 5: Start frontend**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend-next && npm run dev`

Expected: Next.js dev server starts on port 3000.

- [ ] **Step 6: Verify home page**

Open `http://localhost:3000`. Verify:
- Card grid with "Segment Builder" and "Template Builder" cards
- Both cards are clickable links

- [ ] **Step 7: Verify template agent**

Click "Template Builder". In the sidebar, type "A welcome email for new SaaS users with a hero image and CTA button". Verify:
- Activity indicator shows during generation
- Template preview renders with subject, sections, HTML
- Assistant message appears with summary

- [ ] **Step 8: Verify segment agent unchanged**

Navigate to `/segment`. Send a segment query. Verify the 8-step pipeline still works identically.

- [ ] **Step 9: Verify template modification**

On the template page (after initial generation), type "Change the CTA button to blue and add a testimonials section". Verify:
- Template updates with new version number
- Preview shows changes

- [ ] **Step 10: Verify reconnection**

During template generation, reload the browser. Verify:
- Catches up from checkpointer (template state restored if run completed)
- Or bridges to live Pub/Sub if still running
