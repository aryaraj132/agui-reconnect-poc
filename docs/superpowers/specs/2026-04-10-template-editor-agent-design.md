# Template Editor Agent — Design Spec

## Overview

Add a new "Template Editor" agent alongside the existing Template Builder. The editor supports two modes of AI-assisted template creation:

1. **FE-tools mode** — Backend agent emits AG-UI tool calls that the frontend auto-executes (state-push pattern)
2. **BE-only mode** — Backend agent executes the same tools locally against state, delivers final result via STATE_SNAPSHOT

Both modes use `create_react_agent` (not StateGraph). The existing template agent sub-graphs (analysis + quality check) become optional tools available in both modes.

Users can also **drag-and-drop components** onto a canvas without AI involvement, then ask AI to improve what they built. UI interactions are locked while AI is generating.

A NavBar toggle switches between FE-tools and BE-only modes. Toggling resets the thread (new session). Reconnection on reload is supported via checkpointer state — same pattern as existing template agent.

---

## Backend Architecture

### Directory Structure

```
src/stream_reconnection_demo/agent/template_editor/
├── __init__.py
├── state.py              # Shared state (TemplateEditorState)
├── tools.py              # Shared tool schemas + BE-side executors
├── fe_tool_agent.py      # create_react_agent — emits tool calls to FE
├── be_only_agent.py      # create_react_agent — executes tools locally
└── routes.py             # /api/v1/template-editor/fe-tools
                          # /api/v1/template-editor/be-only
```

### State (`state.py`)

Reuses `EmailTemplate` schema. State shape is identical for both modes:

- `messages: list` — chat history (with `add` reducer)
- `template: dict | None` — full EmailTemplate (sections, html, css, subject, preview_text, version)
- `error: str | None`
- `version: int`

### Tools (`tools.py`)

Symmetric tool definitions used by both agents:

| Tool | Parameters | Description |
|------|-----------|-------------|
| `add_section` | `type`, `content`, `position?` | Adds a section (header/body/footer/cta/image/divider/spacer/social_links/text_block/columns) |
| `update_section` | `section_id`, `content?`, `styles?` | Modifies an existing section |
| `remove_section` | `section_id` | Removes a section |
| `reorder_sections` | `section_ids: list` | Reorders sections |
| `update_metadata` | `subject?`, `preview_text?` | Updates subject/preview_text |
| `analyze_template` | — | Invokes analysis sub-graph (optional, agent decides) |
| `quality_check` | — | Invokes quality check sub-graph (optional, agent decides) |
| `assemble_html` | — | Rebuilds full HTML from sections |

### FE Tool Agent (`fe_tool_agent.py`)

- `create_react_agent` with tools defined as CopilotKit-compatible tool calls
- When the agent calls `add_section`, it emits an AG-UI tool call event -> FE auto-executes -> state updates on FE -> state syncs back
- Analysis/quality tools always execute on BE (sub-graph invocation)

### BE Only Agent (`be_only_agent.py`)

- `create_react_agent` with the same tool schemas, but all tool functions execute locally against the agent state
- When the agent calls `add_section`, the tool function directly mutates state, builds HTML, returns result
- No FE tool calls emitted — final output rendered via STATE_SNAPSHOT

### Routes (`routes.py`)

- Two POST endpoints following the same pattern as template agent routes
- Each has its own checkpointer, reconnect config, and event streaming
- Both support `requestType: "connect"` for reconnection
- Shared `ReconnectConfig` works for both (same state shape)

### Registration (`main.py`)

- Build both agents with separate checkpointers in lifespan
- Include the new router

---

## Frontend Architecture

### New Files

```
frontend-next/
├── app/
│   ├── template-editor/
│   │   └── page.tsx              # Single page for both modes
│   └── api/copilotkit/
│       └── template-editor/
│           ├── fe-tools/route.ts  # Proxy to /api/v1/template-editor/fe-tools
│           └── be-only/route.ts   # Proxy to /api/v1/template-editor/be-only
├── components/
│   ├── TemplateEditorCanvas.tsx   # Main layout: palette sidebar + canvas + preview
│   ├── ComponentPalette.tsx       # Draggable component list
│   └── SectionDropZone.tsx        # Drop target area where sections render
└── lib/
    └── template-components.ts     # Component registry (type -> default content/styles)
```

### Page (`template-editor/page.tsx`)

- Single page component, same structure as existing `template/page.tsx`
- `mode` state: `"fe-tools"` | `"be-only"` (default: `"fe-tools"`)
- Switches `runtimeUrl` between the two API routes based on mode
- On mode toggle -> generates new thread ID (forces `CopilotKit` remount via `key={threadId}`)
- Registers CopilotKit actions for FE tools (`add_section`, `update_section`, etc.) — auto-executed state-push handlers
- In BE-only mode, these actions still exist but won't be invoked

### NavBar Toggle

- Added to `Nav` component, visible only on `/template-editor` route
- Toggle switch: "FE Tools" | "BE Only"
- Confirmation toast: "Switching mode will start a new session"
- Calls callback that resets thread + switches mode

### Drag & Drop

- `ComponentPalette`: vertical sidebar listing all 10 component types with icons
- User drags component -> drops onto `SectionDropZone`
- On drop: creates `TemplateSection` with default content, appends to sections, reassembles HTML
- Pure FE state manipulation — no AI call
- **Locked during AI generation**: drag handles, drop targets, and inline editing disabled while `inProgress` is true. Subtle overlay/opacity indicates "AI is working"

### Component Registry (`template-components.ts`)

Maps each type to: `{ label, icon, defaultContent, defaultStyles }`

Types: header, body, footer, cta, image, divider, spacer, social_links, text_block, columns

### CopilotKit FE Tool Handlers

Registered via `useCopilotAction`:
- `add_section` -> pushes new section, reassembles HTML
- `update_section` -> finds by ID, merges changes, reassembles
- `remove_section` -> filters out section, reassembles
- `reorder_sections` -> reorders by ID list, reassembles
- `update_metadata` -> updates subject/preview_text

### Home Page & Nav

- New card on home page for "Template Editor"
- New tab in Nav component

---

## Data Flow

### Primary Journey: Manual drag-drop + AI improvement

1. User drags components onto canvas -> state builds locally
2. User types improvement request in sidebar chat
3. CopilotKit sends state (current sections/html) + message to backend
4. Agent receives full state context, decides which tools to call
5. **FE-tools mode:** Agent emits tool calls -> FE auto-executes -> state updates live
6. **BE-only mode:** Agent calls same tools locally -> STATE_SNAPSHOT -> FE renders
7. Agent optionally calls `analyze_template` / `quality_check`

### State Synchronization

- State shape identical regardless of mode
- FE holds canonical state via `useCoAgent<EmailTemplate>()`
- Each chat request sends current FE state to backend
- Backend reads state to understand what user has built

### Reconnection

- Checkpointer-based (same as existing template agent)
- On reload -> `agent/connect` -> backend reads checkpointer -> emits synthetic catch-up (STATE_SNAPSHOT)
- FE receives state -> renders sections on canvas + preview
- One `ReconnectConfig` works for both modes (same state shape)

---

## Error Handling & Edge Cases

- **Drag-drop without AI:** Purely client-side. No thread until first chat.
- **Mode switch:** Resets thread (new UUID). Previous thread persists in checkpointer, accessible via browser history.
- **Empty state on reconnect:** Emit empty RUN_STARTED + RUN_FINISHED. FE shows blank canvas.
- **Tool call failures (FE mode):** Error returned to agent, can retry/adjust.
- **UI lock during generation:** Palette drag, drop targets, inline editing all disabled while AI is running. Re-enabled on completion.

---

## Playwright Test Scope

### Prerequisites

- Backend running on `localhost:8000`
- Frontend (Next.js) running on `localhost:3000`
- Tests use Playwright MCP browser tools (snapshot-based interaction, not selectors)

### Test Suite 1: Navigation & Discovery

**T1.1 — Home page shows Template Editor card**
1. Navigate to `/`
2. Verify "Template Editor" card exists with description
3. Click it -> verify navigation to `/template-editor`

**T1.2 — Nav bar shows Template Editor tab**
1. Navigate to `/template-editor`
2. Verify "Template Editor" tab is active in nav
3. Verify mode toggle is visible (defaults to "FE Tools")

### Test Suite 2: Drag & Drop (No AI)

**T2.1 — Component palette renders all component types**
1. Navigate to `/template-editor`
2. Verify palette sidebar shows all 10 component types: Header, Body, Footer, CTA, Image, Divider, Spacer, Social Links, Text Block, Columns

**T2.2 — Drag and drop a Header component**
1. Drag "Header" from palette to drop zone
2. Verify a header section appears on canvas
3. Verify HTML preview updates in the iframe
4. Verify state has 1 section of type "header"

**T2.3 — Drag multiple components to build a template**
1. Drag Header, Text Block, CTA, Footer (in order)
2. Verify 4 sections appear in correct order
3. Verify each section has expected default content
4. Verify assembled HTML contains all sections

**T2.4 — Remove a section from canvas**
1. Build a 3-section template via drag-drop
2. Remove the middle section
3. Verify only 2 sections remain
4. Verify HTML re-assembles without the removed section

### Test Suite 3: FE-Tools Mode (AI Generation)

**T3.1 — AI improves a manually-built template**
1. Drag Header + Text Block + CTA onto canvas
2. Type in sidebar: "Make this template more professional with better colors"
3. Wait for AI response to complete
4. Verify template state has been updated (tool calls executed)
5. Verify HTML preview shows the updated template

**T3.2 — UI is locked during AI generation**
1. Drag a Header onto canvas
2. Type improvement request in sidebar
3. While AI is generating: verify palette drag handles are disabled
4. While AI is generating: verify drop zone does not accept drops
5. After completion: verify drag-drop is re-enabled

**T3.3 — AI can add sections via FE tool calls**
1. Start with empty canvas
2. Type: "Add a header, a body paragraph, and a CTA button"
3. Verify sections appear on canvas as tool calls execute
4. Verify final state has 3+ sections

### Test Suite 4: BE-Only Mode

**T4.1 — Toggle to BE-only mode**
1. Navigate to `/template-editor`
2. Click mode toggle to "BE Only"
3. Verify thread resets (new URL thread param)
4. Verify canvas is empty (fresh session)

**T4.2 — AI generates template in BE-only mode**
1. Toggle to BE-only mode
2. Drag Header + Text Block onto canvas
3. Type: "Improve this template with better styling"
4. Wait for response
5. Verify template state updates via STATE_SNAPSHOT (not tool calls)
6. Verify final template renders in preview

**T4.3 — Both modes produce comparable results**
1. In FE-tools mode: drag Header + CTA, ask AI "make it look like a welcome email"
2. Note the resulting template structure
3. Toggle to BE-only mode (new thread)
4. Drag Header + CTA, ask AI same prompt
5. Verify both produce templates with similar section structure

### Test Suite 5: Reconnection

**T5.1 — Reconnect after drag-drop + AI completion (FE-tools)**
1. In FE-tools mode: drag components, chat with AI, wait for completion
2. Note the final template state (subject, section count, version)
3. Reload the page
4. Verify template restores on canvas (same subject, sections, version)
5. Verify chat history restores in sidebar

**T5.2 — Reconnect after AI completion (BE-only)**
1. In BE-only mode: chat with AI to generate template
2. Note final state
3. Reload page
4. Verify template restores

**T5.3 — Reconnect with empty state**
1. Navigate to `/template-editor` with a new thread
2. Reload without doing anything
3. Verify blank canvas loads without errors

### Test Suite 6: Mode Toggle Behavior

**T6.1 — Toggle preserves previous thread in history**
1. In FE-tools mode: build a template
2. Toggle to BE-only mode
3. Press browser back
4. Verify previous FE-tools thread URL restores
5. Verify template from that thread loads via reconnection

**T6.2 — Toggle back and forth**
1. Start in FE-tools, drag a header
2. Toggle to BE-only, drag a different component
3. Toggle back to FE-tools
4. Verify fresh canvas (new thread, not the old FE-tools thread)

### Test Suite 7: Sub-graph Tools

**T7.1 — Analysis tool invocation**
1. Build a template (either mode)
2. Ask AI: "Analyze this template for accessibility issues"
3. Verify analysis results appear in reasoning panel in sidebar

**T7.2 — Quality check tool invocation**
1. Build a template (either mode)
2. Ask AI: "Run a quality check on this template"
3. Verify quality results appear in chat
