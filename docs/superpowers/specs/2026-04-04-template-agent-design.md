# Template Agent Integration Design

## Overview

Add an email template creation/modification agent to the project using the `ag-ui-langgraph` library. The template agent runs alongside the existing segment agent (unchanged). It uses `LangGraphAgent.run()` for automatic AG-UI event generation, Redis Pub/Sub for live streaming (no Redis List), and LangGraph checkpointer as the single source of truth for catch-up on reconnect.

## Architecture

```
Graph Nodes (generate_template / modify_template)
     |
     v
LangGraphAgent.run()      <- auto: RUN_*, STEP_*, STATE_SNAPSHOT, TEXT_MESSAGE_*, REASONING_* (LLM)
     |
     v
EventAdapter               <- translates CUSTOM events, filters STATE_SNAPSHOT, encodes to SSE strings
     |
     v
agent_runner               <- publishes SSE strings to Redis Pub/Sub (no List)
     |
     v
Redis Pub/Sub              <- live events to client
     |
LangGraph Checkpointer     <- single source of truth for catch-up on reconnect
```

### Request Flows

**New run (chat):**
1. `_handle_chat()` creates `RunAgentInput` from request
2. `EventAdapter.stream_events(agent, input)` yields SSE strings
3. `start_agent_task_pubsub_only()` publishes each SSE string to Pub/Sub
4. Client subscribes via `pubsub.subscribe_and_stream()`

**Reconnect (connect):**
1. Check Redis for active run
2. If active: subscribe to Pub/Sub first (buffer live events), read checkpointer state, emit synthetic catch-up (MESSAGES_SNAPSHOT, STATE_SNAPSHOT with template data), yield live Pub/Sub events
3. If completed: replay from checkpointer (full state)
4. If nothing: empty run (RUN_STARTED + RUN_FINISHED)

**Duplicate query:**
- Detect duplicate via checkpointer's last human message
- Return minimal run: RUN_STARTED + STATE_SNAPSHOT (replay template) + RUN_FINISHED

## Backend

### Schema: `schemas/template.py`

Pydantic models matching the reference project exactly:

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

### State: `agent/template/state.py`

```python
class TemplateAgentState(TypedDict):
    messages: Annotated[list, add]   # LangChain messages (accumulated via reducer)
    template: dict | None            # Current template dict (None = first generation)
    error: str | None                # Error message if generation failed
    version: int                     # Template version counter

class TemplateOutput(TypedDict):
    template: dict | None            # Output schema limits STATE_SNAPSHOT to template only
```

`TemplateOutput` is the graph's output schema. This ensures the library's auto-generated STATE_SNAPSHOT events only include `{template: ...}` rather than the full internal state (messages, error, version).

### Graph: `agent/template/graph.py`

Two-node graph with conditional routing:

**Nodes:**
- `generate_template`: Creates a new template from user description. Uses `ChatAnthropic.with_structured_output(EmailTemplate)`. Dispatches activity custom events.
- `modify_template`: Modifies existing template based on user request. System prompt includes current template context (subject, sections summary, HTML). Increments version. Dispatches activity custom events.

**Routing:**
- `_route_by_state(state)`: If `state["template"] is None` -> `"generate_template"`, else -> `"modify_template"`

**Custom events dispatched from nodes:**
Each node dispatches `adispatch_custom_event` for:
- `"activity_snapshot"`: Progress indicators (`{"title": "Generating template", "progress": 0.1, "details": "Starting LLM generation..."}`)

**Graph construction:**
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

**System prompts:** Reuse the same prompts from the reference project's graph.py (GENERATE_SYSTEM_PROMPT, MODIFY_SYSTEM_PROMPT).

### EventAdapter: `core/event_adapter.py`

Bridges `LangGraphAgent.run()` output to SSE strings. This is a reusable module for any `ag-ui-langgraph` agent.

**Responsibilities:**
1. Iterate over `agent.run(input_data)` which yields AG-UI event objects
2. Intercept `EventType.CUSTOM` events and translate:
   - `"activity_snapshot"` -> `ActivitySnapshotEvent`
3. Filter `EventType.STATE_SNAPSHOT`: suppress intermediate `{template: null}` snapshots, pass through the final snapshot with actual template data
4. After `RUN_STARTED`: inject empty `StateSnapshotEvent(snapshot={})` to reset frontend co-agent state
5. Encode each event via `EventEncoder.encode()` -> yields SSE strings

**Interface:** `stream_events(agent, input_data) -> AsyncIterator[str]` — same `AsyncIterator[str]` interface as `run_segment_pipeline()` / `run_stateful_segment_pipeline()`, so `agent_runner` needs zero changes.

```python
class EventAdapter:
    def __init__(self):
        self._encoder = EventEncoder()

    async def stream_events(self, agent: LangGraphAgent, input_data: RunAgentInput) -> AsyncIterator[str]:
        async for event_obj in agent.run(input_data):
            if event_obj.type == EventType.CUSTOM:
                async for translated in self._translate_custom(event_obj):
                    yield self._encoder.encode(translated)
                continue

            if event_obj.type == EventType.STATE_SNAPSHOT:
                snapshot = event_obj.snapshot or {}
                if snapshot.get("template") is None:
                    continue  # suppress intermediate empty snapshot

            if event_obj.type == EventType.RUN_STARTED:
                yield self._encoder.encode(event_obj)
                yield self._encoder.encode(StateSnapshotEvent(snapshot={}))
                continue

            yield self._encoder.encode(event_obj)

    async def _translate_custom(self, event_obj):
        name = event_obj.name
        data = event_obj.value

        if name == "activity_snapshot":
            yield ActivitySnapshotEvent(
                message_id=str(uuid.uuid4()),
                activity_type="processing",
                content=data,
            )
```

### Routes: `agent/template/routes.py`

POST `/api/v1/template` — single endpoint handling chat, connect, and duplicate flows.

**Request body:**
```json
{
    "thread_id": "uuid",
    "run_id": "uuid",
    "messages": [{"id": "...", "role": "user", "content": "..."}],
    "state": { "subject": "...", "sections": [...] },
    "metadata": { "requestType": "chat" | "connect" }
}
```

**`_handle_chat(pubsub, template_graph, template_agent, thread_id, run_id, query, frontend_state)`:**
1. Duplicate query check via checkpointer (same pattern as stateful_segment)
2. If duplicate: return minimal run with STATE_SNAPSHOT replay
3. `pubsub.start_run(thread_id, run_id)`
4. Build `RunAgentInput` with messages, state (frontend_state for modify flow), thread_id, run_id
5. `EventAdapter().stream_events(template_agent, input_data)` -> `start_agent_task_pubsub_only(pubsub, template_graph, thread_id, run_id, event_stream)`
6. `asyncio.sleep(0.1)` then return `StreamingResponse(pubsub.subscribe_and_stream(...))`

**`_handle_connect(pubsub, template_graph, thread_id, run_id)`:**
Same pattern as `_handle_stateful_connect` in stateful_segment/routes.py:
- Active run: Pub/Sub subscribe first -> checkpointer state catch-up -> live Pub/Sub events
- Completed: checkpointer state replay
- Nothing: empty run

**Synthetic catch-up `_emit_synthetic_catchup(state, thread_id, run_id)`:**
- Emit RUN_STARTED
- Emit MESSAGES_SNAPSHOT from checkpointer messages
- Emit STATE_SNAPSHOT with template data (if exists)
- (No progress stepper — template agent is a single-step LLM call, no multi-node progress)

**GET `/api/v1/template/state/{thread_id}`:**
Direct checkpointer read, return `{template: ...}` or `{template: null}`.

### main.py Changes

In lifespan, add:
```python
from ag_ui_langgraph import LangGraphAgent
from stream_reconnection_demo.agent.template.graph import build_template_graph
from stream_reconnection_demo.agent.template.routes import router as template_router

# In lifespan:
template_checkpointer = MemorySaver()
template_graph = build_template_graph(checkpointer=template_checkpointer)
app.state.template_graph = template_graph  # for checkpointer reads in _handle_connect
app.state.template_agent = LangGraphAgent(name="template", graph=template_graph)

# Register router:
app.include_router(template_router)
```

### Dependency: `pyproject.toml`

Add `"ag-ui-langgraph>=0.0.29"` to dependencies list.

## Frontend

### API Route: `app/api/copilotkit/template/route.ts`

Same pattern as the segment API route:

```typescript
import { CopilotRuntime, EmptyAdapter, copilotRuntimeNextJSAppRouterEndpoint } from "@copilotkit/runtime";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

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

### Types: `lib/types.ts`

Add EmailTemplate types:

```typescript
export interface TemplateSection {
    id: string;
    type: string;  // header | body | footer | cta | image
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

### Template Page: `app/template/page.tsx`

Structure follows the reference project pattern:

```
TemplatePage (Suspense wrapper)
  -> TemplatePageInner (useAgentThread)
      -> CopilotKit (runtimeUrl="/api/copilotkit/template", threadId)
          -> CopilotSidebar (defaultOpen=true, RenderMessage=CustomRenderMessage)
              -> TemplatePageContent
                  - useCoAgent<EmailTemplate>({ name: "default" }) -> template state
                  - useCoAgentStateRender -> inline template update notification in chat
                  - Content: Nav + TemplateEditor (when template exists) or placeholder
```

**CustomRenderMessage:** Same pattern as segment page — filter old reasoning/activity messages, render user/assistant messages.

**Labels:** Title "Template Creator", initial message prompting user to describe their email template.

### TemplateEditor Component: `components/TemplateEditor.tsx`

Replicates the reference project's TemplateEditor:
- Metadata bar: subject, preview text, version number
- Editable preview via iframe (TemplatePreview component)
- HTML content rendered in sandboxed iframe with designMode for inline editing

### TemplatePreview Component: `components/TemplatePreview.tsx`

Replicates the reference project's TemplatePreview:
- Sandboxed iframe rendering the template HTML+CSS
- Optional designMode editing (contentEditable)
- Callback on HTML changes for live editing

### Home Page: `app/page.tsx`

Replace the current redirect-to-segment with a card grid:

```tsx
export default function Home() {
    return (
        <main className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 p-8 max-w-3xl">
                <Card href="/segment" title="Segment Builder" description="Build audience segments with an 8-step AI pipeline. Features stream reconnection with Redis Pub/Sub." />
                <Card href="/template" title="Template Builder" description="Create and modify email templates with AI. Uses ag-ui-langgraph for automatic event generation." />
            </div>
        </main>
    );
}
```

### Nav Component: `components/Nav.tsx`

Update to show both agent tabs with active state based on current path:

```tsx
export function Nav() {
    const pathname = usePathname();
    return (
        <header>
            <Link href="/">Stream Reconnection Demo</Link>
            <nav>
                <Link href="/segment" className={pathname === "/segment" ? "active" : ""}>Segment Builder</Link>
                <Link href="/template" className={pathname === "/template" ? "active" : ""}>Template Builder</Link>
            </nav>
        </header>
    );
}
```

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Edit | Add `ag-ui-langgraph>=0.0.29` |
| `schemas/template.py` | New | EmailTemplate + TemplateSection Pydantic models |
| `agent/template/__init__.py` | New | Package init |
| `agent/template/state.py` | New | TemplateAgentState + TemplateOutput TypedDicts |
| `agent/template/graph.py` | New | LangGraph with generate/modify nodes + conditional routing + custom events |
| `agent/template/routes.py` | New | POST endpoint with chat/connect/duplicate flows |
| `core/event_adapter.py` | New | Bridges LangGraphAgent.run() -> SSE strings |
| `main.py` | Edit | Add template graph, LangGraphAgent, router in lifespan |
| `frontend-next/app/page.tsx` | Edit | Card grid home page replacing redirect |
| `frontend-next/app/template/page.tsx` | New | Template agent page with CopilotKit |
| `frontend-next/app/api/copilotkit/template/route.ts` | New | CopilotKit proxy with connect interceptor |
| `frontend-next/components/TemplateEditor.tsx` | New | Template metadata bar + preview wrapper |
| `frontend-next/components/TemplatePreview.tsx` | New | Sandboxed iframe HTML preview with editing |
| `frontend-next/components/Nav.tsx` | Edit | Add template tab with active state |
| `frontend-next/lib/types.ts` | Edit | Add EmailTemplate + TemplateSection interfaces |
| All segment agent files | Unchanged | Segment code stays as-is |
| `core/events.py` | Unchanged | Still used by segment agent + template catch-up handlers |
| `core/pubsub.py` | Unchanged | Shared Redis Pub/Sub infrastructure |
| `core/agent_runner.py` | Unchanged | `start_agent_task_pubsub_only()` reused by template agent |

## Key Design Decisions

1. **`ag-ui-langgraph` for template agent only** — The segment agent retains its manual event emission pattern. This is a contained integration that proves the library works before any broader migration.

2. **EventAdapter as the seam** — Isolates all `ag-ui-langgraph` interaction to one reusable module. `agent_runner` sees the same `AsyncIterator[str]` interface. If the segment agent migrates later, it can reuse this adapter.

3. **Checkpointer as single source of truth** — No Redis List for the template agent. The checkpointer stores conversation state persistently. Catch-up on reconnect reads from checkpointer. Redis Pub/Sub is ephemeral, used only for live event delivery.

4. **Same reconnection pattern as stateful_segment** — `_handle_connect` follows the established pattern: Pub/Sub subscribe first (buffer), checkpointer read, synthetic catch-up events, live Pub/Sub bridging.

5. **Graph output schema (`TemplateOutput`)** — Limits STATE_SNAPSHOT to `{template: ...}` only. The EventAdapter adds fine-tuning: suppresses `{template: null}` intermediate snapshots.

6. **Frontend state via `useCoAgent`** — Same pattern as segment page. Template state flows from backend STATE_SNAPSHOT -> CopilotKit -> `useCoAgent<EmailTemplate>` hook -> TemplateEditor/TemplatePreview components.

## Verification

1. `uv sync` — ensure `ag-ui-langgraph` dependency resolves
2. Start Redis + backend + frontend
3. **Home page**: Verify card grid with links to both agents
4. **New template**: Navigate to `/template`, type "welcome email for SaaS" -> verify template generation with activity indicator, final template card rendering
5. **Modify template**: After generation, type "change the CTA to blue" -> verify template updates with version increment
6. **Reconnect mid-generation**: Reload browser while template is generating -> verify catch-up from checkpointer, live Pub/Sub resume
7. **Reconnect after completion**: Reload browser after template is done -> verify full state replay from checkpointer (template card rendered)
8. **Duplicate prevention**: After template is done, verify CopilotKit re-send returns minimal run with template state preserved
9. **Segment agent unchanged**: Navigate to `/segment`, verify all existing functionality works identically
