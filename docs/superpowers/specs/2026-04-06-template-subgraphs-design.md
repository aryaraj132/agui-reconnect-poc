# Template Agent Subgraph Integration Design

**Date:** 2026-04-06
**Purpose:** Add two subgraphs to the template agent to test ag-ui-langgraph's subgraph event streaming behavior, then document findings.

## Goals

1. Add an **HTML Analysis** subgraph (Approach A — native LangGraph composition via `add_node`) with parallel fan-out/fan-in nodes
2. Add a **Content Quality Check** subgraph (Approach B — manual `ainvoke` inside a wrapper node)
3. Test whether ag-ui-langgraph streams events from subgraph nodes when `stream_subgraphs=True` vs `False`
4. Investigate the library's `stream_subgraphs` forwarded prop (the user initially thought there was a `stream_mode` property — there is not)
5. Document all findings in a new section of `ag-ui-langgraph-walkthrough.md`

## Key Discovery: No `stream_mode` on LangGraphAgent

The library does **not** have a `stream_mode` property. It exclusively uses `astream_events()` (LangChain callback-level streaming), not LangGraph's `.stream(stream_mode=...)`. The only subgraph-related config is `stream_subgraphs` passed via `RunAgentInput.forwarded_props`, which maps to `astream_events(subgraphs=True/False)`.

In `agent.py` lines 193-198, the library detects subgraph events via an `is_subgraph_stream` flag but **never uses it for filtering** — events flow through unfiltered when enabled.

## Architecture

### Updated Template Agent Graph

```
START → route_by_state → generate_template ──┐
                       → modify_template  ───┤
                                              ▼
                                   analyze_template (Subgraph A — native composition)
                                      ├─ analyze_subject    (parallel)
                                      ├─ analyze_colors     (parallel)
                                      ├─ analyze_typography (parallel)
                                      └─ analyze_structure  (parallel)
                                              ▼
                                      overall_analysis → (conditional)
                                              ├─ apply_improvements → (end subgraph)
                                              └─ (end subgraph, no changes needed)
                                              ▼
                                   quality_check_node (wrapper calling Subgraph B via ainvoke)
                                      Internally: check_spelling → check_tone → check_cta → aggregate_quality
                                              ▼
                                            END
```

### Subgraph A: HTML Analysis (Native Composition)

- Compiled `StateGraph` added directly via `parent_graph.add_node("analyze_template", compiled_analysis_graph)`
- LangGraph treats this as a true subgraph — `astream_events()` emits events with namespaced paths
- 4 parallel analysis nodes (separate named nodes, not `Send()` API) for clear event identification
- `overall_analysis` node synthesizes findings and sets `needs_improvement` flag
- Conditional edge to `apply_improvements` (only if needed)
- All nodes use real `ChatAnthropic` LLM calls
- No custom events (`adispatch_custom_event`) — pure test of automatic streaming

### Subgraph B: Content Quality Check (Manual `ainvoke`)

- Separate compiled `StateGraph` with its own isolated state
- Invoked from a wrapper node via `analysis_graph.ainvoke()`
- Linear pipeline: `check_spelling` → `check_tone` → `check_cta` → `aggregate_quality`
- All nodes use real `ChatAnthropic` LLM calls
- Wrapper node maps template in and quality_summary out

## State Schemas

### Analysis Subgraph State (Subgraph A — shares keys with parent)

```python
class AnalysisResult(TypedDict):
    aspect: str              # "subject", "colors", "typography", "structure"
    findings: str            # LLM analysis output
    suggestions: list[str]   # Specific improvement suggestions
    severity: str            # "low", "medium", "high"

class AnalysisSubgraphState(TypedDict):
    template: dict | None
    analyses: Annotated[list[AnalysisResult], operator.add]  # Fan-in via reducer
    overall_assessment: str | None
    needs_improvement: bool
    improved_template: dict | None
```

### Quality Check Subgraph State (Subgraph B — fully isolated)

```python
class QualityCheckState(TypedDict):
    template: dict | None
    spelling_report: str | None
    tone_report: str | None
    cta_report: str | None
    quality_summary: str | None
```

### Updated Parent State

```python
class TemplateAgentState(TypedDict):
    messages: Annotated[list, add]
    template: dict | None
    error: str | None
    version: int
    # New fields for subgraph A (native composition shares state):
    analyses: Annotated[list[AnalysisResult], operator.add]
    overall_assessment: str | None
    needs_improvement: bool
    # New field from subgraph B (mapped manually by wrapper):
    quality_summary: str | None

class TemplateOutput(TypedDict):
    template: dict | None
    quality_summary: str | None
```

## Node Implementations

### Subgraph A Nodes

All use real LLM calls via `ChatAnthropic`, no custom events.

1. **`analyze_subject`** — Analyzes subject line effectiveness (length, urgency, personalization). Returns `AnalysisResult` with `aspect="subject"`.

2. **`analyze_colors`** — Analyzes CSS color scheme (brand consistency, contrast, accessibility). Returns `AnalysisResult` with `aspect="colors"`.

3. **`analyze_typography`** — Analyzes font choices, sizes, line heights, readability. Returns `AnalysisResult` with `aspect="typography"`.

4. **`analyze_structure`** — Analyzes HTML structure (mobile-responsiveness, table layout, section hierarchy). Returns `AnalysisResult` with `aspect="structure"`.

5. **`overall_analysis`** — Receives all 4 analyses, synthesizes overall assessment. Sets `needs_improvement=True/False`.

6. **`apply_improvements`** — Conditional (only if `needs_improvement=True`). Takes template + analyses, produces improved template.

### Subgraph B Nodes

All use real LLM calls, linear pipeline.

1. **`check_spelling`** — Checks grammar, spelling, punctuation in template text content.
2. **`check_tone`** — Checks tone consistency across sections.
3. **`check_cta`** — Evaluates call-to-action effectiveness.
4. **`aggregate_quality`** — Combines reports into quality summary string.

## Event Adapter Changes

The existing `EventAdapter` filters `STATE_SNAPSHOT` by `state_snapshot_key="template"`. This remains unchanged — the frontend only needs `template` and `quality_summary`, not internal analysis state.

The `TemplateOutput` schema on the graph controls what gets emitted in state snapshots, so internal fields (`analyses`, `overall_assessment`, `needs_improvement`) are automatically excluded.

## Testing Plan

### Test 1: Default behavior (stream_subgraphs disabled)

- `forwarded_props={}` (current default)
- Expected: Only parent-level events visible (text streaming from generate/modify nodes)
- Question: Do we see any events from subgraph nodes?

### Test 2: stream_subgraphs enabled

- `forwarded_props={"stream_subgraphs": True}`
- Expected for Subgraph A (native): Events from all internal nodes with namespaced paths
- Expected for Subgraph B (ainvoke): Likely NO internal events visible (hidden inside wrapper node execution)

### Test 3: Event comparison

- Log all raw events from both tests
- Compare event types, namespaces, and node names
- Document which AG-UI event types appear from subgraph nodes

## Walkthrough Documentation

After implementation and testing, add a new section to `ag-ui-langgraph-walkthrough.md` covering:

1. How LangGraph subgraphs work (native composition vs manual ainvoke)
2. How ag-ui-langgraph handles subgraph events (`stream_subgraphs` prop)
3. The `is_subgraph_stream` detection code and its unused state
4. Test results: what events appear/don't appear for each approach
5. The `stream_mode` misconception (library uses `astream_events()`, not `.stream()`)
6. Recommendations for when to use each approach

## Files to Create/Modify

### New files:
- `src/stream_reconnection_demo/agent/template/analysis_graph.py` — HTML analysis subgraph (Subgraph A)
- `src/stream_reconnection_demo/agent/template/quality_graph.py` — Content quality check subgraph (Subgraph B)

### Modified files:
- `src/stream_reconnection_demo/agent/template/state.py` — Add new TypedDicts and update TemplateAgentState/TemplateOutput
- `src/stream_reconnection_demo/agent/template/graph.py` — Integrate both subgraphs, add wrapper node for B
- `src/stream_reconnection_demo/agent/template/routes.py` — Add `stream_subgraphs` to `forwarded_props` (configurable)
- `ag-ui-langgraph-walkthrough.md` — New section documenting subgraph findings
