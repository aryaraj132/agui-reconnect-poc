# Template Agent Subgraphs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two subgraphs to the template agent — one via native LangGraph composition (Approach A) and one via manual `ainvoke` (Approach B) — to test ag-ui-langgraph's subgraph event streaming behavior, then document findings.

**Architecture:** The template agent graph extends from 2 nodes to 4 nodes, with a native HTML analysis subgraph (6 internal nodes with fan-out/fan-in) and a content quality check subgraph (4 nodes, linear pipeline) invoked via `ainvoke` inside a wrapper node. Both subgraphs use real LLM calls. After generate/modify, the flow is: analyze_template → quality_check → END.

**Tech Stack:** LangGraph (StateGraph, fan-out/fan-in), ChatAnthropic (structured output), ag-ui-langgraph (LangGraphAgent with stream_subgraphs), Pydantic

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/stream_reconnection_demo/agent/template/state.py` | Modify | Add AnalysisResult, AnalysisSubgraphState, QualityCheckState, update TemplateAgentState and TemplateOutput |
| `src/stream_reconnection_demo/agent/template/analysis_graph.py` | Create | HTML analysis subgraph (Approach A): 4 parallel analysis nodes, overall_analysis, apply_improvements |
| `src/stream_reconnection_demo/agent/template/quality_graph.py` | Create | Content quality check subgraph (Approach B): 3 check nodes + aggregate |
| `src/stream_reconnection_demo/agent/template/graph.py` | Modify | Integrate both subgraphs into parent graph, add wrapper node for Approach B |
| `src/stream_reconnection_demo/agent/template/routes.py` | Modify | Add `stream_subgraphs` to `forwarded_props` |
| `ag-ui-langgraph-walkthrough.md` | Modify | Add new section documenting subgraph findings |

---

### Task 1: Update State Schemas

**Files:**
- Modify: `src/stream_reconnection_demo/agent/template/state.py`

- [ ] **Step 1: Add AnalysisResult and AnalysisSubgraphState**

Replace the full contents of `state.py` with:

```python
from operator import add
from typing import Annotated, TypedDict


class AnalysisResult(TypedDict):
    """Result from a single analysis node in the HTML analysis subgraph."""
    aspect: str          # "subject", "colors", "typography", "structure"
    findings: str        # LLM analysis output
    suggestions: list[str]  # Specific improvement suggestions
    severity: str        # "low", "medium", "high"


class AnalysisSubgraphState(TypedDict):
    """State for the HTML analysis subgraph (Approach A — native composition)."""
    template: dict | None
    analyses: Annotated[list[AnalysisResult], add]  # Fan-in via reducer
    overall_assessment: str | None
    needs_improvement: bool


class QualityCheckState(TypedDict):
    """State for the content quality check subgraph (Approach B — manual ainvoke)."""
    template: dict | None
    spelling_report: str | None
    tone_report: str | None
    cta_report: str | None
    quality_summary: str | None


class TemplateAgentState(TypedDict):
    messages: Annotated[list, add]
    template: dict | None
    error: str | None
    version: int
    # Subgraph A fields (native composition shares state):
    analyses: Annotated[list[AnalysisResult], add]
    overall_assessment: str | None
    needs_improvement: bool
    # Subgraph B field (mapped manually by wrapper):
    quality_summary: str | None


class TemplateOutput(TypedDict):
    """Output schema — limits STATE_SNAPSHOT to these fields only."""
    template: dict | None
    quality_summary: str | None
```

- [ ] **Step 2: Verify the module imports correctly**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python3 -c "from stream_reconnection_demo.agent.template.state import TemplateAgentState, AnalysisResult, AnalysisSubgraphState, QualityCheckState, TemplateOutput; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/state.py
git commit -m "feat(template): add state schemas for analysis and quality check subgraphs"
```

---

### Task 2: Create HTML Analysis Subgraph (Approach A)

**Files:**
- Create: `src/stream_reconnection_demo/agent/template/analysis_graph.py`

- [ ] **Step 1: Create the analysis subgraph module**

Create `src/stream_reconnection_demo/agent/template/analysis_graph.py` with the following content:

```python
"""HTML analysis subgraph — Approach A (native LangGraph composition).

This subgraph analyzes an email template's HTML across 4 dimensions
in parallel (fan-out/fan-in), synthesizes an overall assessment,
and optionally applies improvements.

When added to the parent graph via ``add_node("analyze_template", compiled_graph)``,
LangGraph treats it as a true subgraph with namespaced events.
"""

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from stream_reconnection_demo.agent.template.state import (
    AnalysisResult,
    AnalysisSubgraphState,
)
from stream_reconnection_demo.schemas.template import EmailTemplate


ANALYSIS_MODEL = "claude-sonnet-4-20250514"


SUBJECT_ANALYSIS_PROMPT = """\
You are an email marketing expert. Analyze the following email template's \
subject line for effectiveness.

## Template
Subject: {subject}
Preview text: {preview_text}

## Evaluate
- Length (ideal: 30-60 characters)
- Urgency and curiosity triggers
- Personalization potential
- Spam trigger words
- Mobile preview truncation risk

Respond with a JSON object:
{{"findings": "your analysis", "suggestions": ["suggestion1", "suggestion2"], "severity": "low|medium|high"}}
"""

COLOR_ANALYSIS_PROMPT = """\
You are a UI/UX designer specializing in email design. Analyze the CSS \
color scheme in this email template.

## Template HTML
{html}

## Evaluate
- Brand color consistency
- Color contrast (WCAG AA compliance)
- Background/foreground readability
- CTA button color prominence
- Dark mode compatibility

Respond with a JSON object:
{{"findings": "your analysis", "suggestions": ["suggestion1", "suggestion2"], "severity": "low|medium|high"}}
"""

TYPOGRAPHY_ANALYSIS_PROMPT = """\
You are a typography expert for digital communications. Analyze the font \
choices and text styling in this email template.

## Template HTML
{html}

## Evaluate
- Web-safe font usage (Arial, Helvetica, Georgia, etc.)
- Font size hierarchy (headings vs body vs footer)
- Line height and readability
- Mobile font size adequacy (min 14px body)
- Font fallback stack completeness

Respond with a JSON object:
{{"findings": "your analysis", "suggestions": ["suggestion1", "suggestion2"], "severity": "low|medium|high"}}
"""

STRUCTURE_ANALYSIS_PROMPT = """\
You are an email HTML developer. Analyze the structural HTML of this \
email template for compatibility and responsiveness.

## Template HTML
{html}

## Evaluate
- Table-based layout correctness
- 600px container constraint
- Mobile responsiveness (percentage widths)
- Image alt text presence
- Section hierarchy and semantic structure

Respond with a JSON object:
{{"findings": "your analysis", "suggestions": ["suggestion1", "suggestion2"], "severity": "low|medium|high"}}
"""

OVERALL_ANALYSIS_PROMPT = """\
You are a senior email template reviewer. You have received analyses \
from 4 specialists examining different aspects of an email template.

## Individual Analyses
{analyses_json}

## Template
Subject: {subject}

## Task
Synthesize these analyses into an overall assessment. Determine whether \
the template needs improvements based on the severity and number of issues found.

Rules:
- If any analysis has severity "high", improvements are needed.
- If 2+ analyses have severity "medium", improvements are needed.
- Otherwise, the template is acceptable.

Respond with a JSON object:
{{"overall_assessment": "your synthesis", "needs_improvement": true|false}}
"""

APPLY_IMPROVEMENTS_PROMPT = """\
You are an expert email template designer. Based on the analysis below, \
apply the suggested improvements to the email template.

## Current Template
Subject: {subject}
Preview text: {preview_text}
HTML:
{html}

Sections:
{sections_json}

## Analysis & Suggestions
{analyses_json}

## Overall Assessment
{overall_assessment}

## Instructions
Apply the improvements suggested by the analyses. Preserve the overall \
design intent but fix the identified issues. Return the complete updated template.
"""


def _parse_analysis_json(text: str) -> dict:
    """Best-effort parse of LLM JSON response."""
    try:
        # Try direct parse
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting from markdown code block
    if "```" in str(text):
        parts = str(text).split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, TypeError):
                continue
    return {"findings": str(text), "suggestions": [], "severity": "low"}


def _build_analyze_subject(llm: ChatAnthropic):
    async def analyze_subject(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        prompt = SUBJECT_ANALYSIS_PROMPT.format(
            subject=template.get("subject", "(no subject)"),
            preview_text=template.get("preview_text", "(no preview)"),
        )
        response = await llm.ainvoke(
            [SystemMessage(content="You are an email analysis expert. Respond only with valid JSON."),
             HumanMessage(content=prompt)],
            config=config,
        )
        parsed = _parse_analysis_json(response.content)
        result: AnalysisResult = {
            "aspect": "subject",
            "findings": parsed.get("findings", ""),
            "suggestions": parsed.get("suggestions", []),
            "severity": parsed.get("severity", "low"),
        }
        return {"analyses": [result]}

    return analyze_subject


def _build_analyze_colors(llm: ChatAnthropic):
    async def analyze_colors(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        prompt = COLOR_ANALYSIS_PROMPT.format(html=template.get("html", ""))
        response = await llm.ainvoke(
            [SystemMessage(content="You are an email analysis expert. Respond only with valid JSON."),
             HumanMessage(content=prompt)],
            config=config,
        )
        parsed = _parse_analysis_json(response.content)
        result: AnalysisResult = {
            "aspect": "colors",
            "findings": parsed.get("findings", ""),
            "suggestions": parsed.get("suggestions", []),
            "severity": parsed.get("severity", "low"),
        }
        return {"analyses": [result]}

    return analyze_colors


def _build_analyze_typography(llm: ChatAnthropic):
    async def analyze_typography(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        prompt = TYPOGRAPHY_ANALYSIS_PROMPT.format(html=template.get("html", ""))
        response = await llm.ainvoke(
            [SystemMessage(content="You are an email analysis expert. Respond only with valid JSON."),
             HumanMessage(content=prompt)],
            config=config,
        )
        parsed = _parse_analysis_json(response.content)
        result: AnalysisResult = {
            "aspect": "typography",
            "findings": parsed.get("findings", ""),
            "suggestions": parsed.get("suggestions", []),
            "severity": parsed.get("severity", "low"),
        }
        return {"analyses": [result]}

    return analyze_typography


def _build_analyze_structure(llm: ChatAnthropic):
    async def analyze_structure(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        prompt = STRUCTURE_ANALYSIS_PROMPT.format(html=template.get("html", ""))
        response = await llm.ainvoke(
            [SystemMessage(content="You are an email analysis expert. Respond only with valid JSON."),
             HumanMessage(content=prompt)],
            config=config,
        )
        parsed = _parse_analysis_json(response.content)
        result: AnalysisResult = {
            "aspect": "structure",
            "findings": parsed.get("findings", ""),
            "suggestions": parsed.get("suggestions", []),
            "severity": parsed.get("severity", "low"),
        }
        return {"analyses": [result]}

    return analyze_structure


def _build_overall_analysis(llm: ChatAnthropic):
    async def overall_analysis(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        analyses = state.get("analyses", [])
        analyses_json = json.dumps(analyses, indent=2)

        prompt = OVERALL_ANALYSIS_PROMPT.format(
            analyses_json=analyses_json,
            subject=template.get("subject", "(no subject)"),
        )
        response = await llm.ainvoke(
            [SystemMessage(content="You are a senior email reviewer. Respond only with valid JSON."),
             HumanMessage(content=prompt)],
            config=config,
        )
        parsed = _parse_analysis_json(response.content)
        return {
            "overall_assessment": parsed.get("overall_assessment", ""),
            "needs_improvement": parsed.get("needs_improvement", False),
        }

    return overall_analysis


def _route_after_overall(state: AnalysisSubgraphState) -> str:
    """Route to apply_improvements or END based on needs_improvement flag."""
    if state.get("needs_improvement", False):
        return "apply_improvements"
    return END


def _build_apply_improvements(llm: ChatAnthropic):
    structured_llm = llm.with_structured_output(EmailTemplate)

    async def apply_improvements(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        analyses = state.get("analyses", [])
        sections_json = json.dumps(
            [{"id": s.get("id"), "type": s.get("type")} for s in template.get("sections", [])],
            indent=2,
        )

        prompt = APPLY_IMPROVEMENTS_PROMPT.format(
            subject=template.get("subject", ""),
            preview_text=template.get("preview_text", ""),
            html=template.get("html", ""),
            sections_json=sections_json,
            analyses_json=json.dumps(analyses, indent=2),
            overall_assessment=state.get("overall_assessment", ""),
        )
        result = await structured_llm.ainvoke(
            [SystemMessage(content="You are an expert email template designer."),
             HumanMessage(content=prompt)],
            config=config,
        )
        return {"template": result.model_dump()}

    return apply_improvements


def build_analysis_graph(model: str = ANALYSIS_MODEL) -> StateGraph:
    """Build the HTML analysis subgraph (not compiled).

    Returns an uncompiled StateGraph so the parent can compile it
    as part of its own compilation, or it can be compiled standalone
    for testing.
    """
    llm = ChatAnthropic(model=model)

    graph = StateGraph(AnalysisSubgraphState)

    # Parallel analysis nodes (fan-out from START)
    graph.add_node("analyze_subject", _build_analyze_subject(llm))
    graph.add_node("analyze_colors", _build_analyze_colors(llm))
    graph.add_node("analyze_typography", _build_analyze_typography(llm))
    graph.add_node("analyze_structure", _build_analyze_structure(llm))

    # Convergence node (fan-in)
    graph.add_node("overall_analysis", _build_overall_analysis(llm))

    # Conditional improvement node
    graph.add_node("apply_improvements", _build_apply_improvements(llm))

    # Fan-out: START → all 4 analysis nodes
    graph.add_edge(START, "analyze_subject")
    graph.add_edge(START, "analyze_colors")
    graph.add_edge(START, "analyze_typography")
    graph.add_edge(START, "analyze_structure")

    # Fan-in: all 4 → overall_analysis
    graph.add_edge("analyze_subject", "overall_analysis")
    graph.add_edge("analyze_colors", "overall_analysis")
    graph.add_edge("analyze_typography", "overall_analysis")
    graph.add_edge("analyze_structure", "overall_analysis")

    # Conditional: overall_analysis → apply_improvements or END
    graph.add_conditional_edges("overall_analysis", _route_after_overall)

    graph.add_edge("apply_improvements", END)

    return graph
```

- [ ] **Step 2: Verify the module imports and graph builds correctly**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python3 -c "from stream_reconnection_demo.agent.template.analysis_graph import build_analysis_graph; g = build_analysis_graph(); c = g.compile(); print('Nodes:', list(c.get_graph().nodes.keys())); print('OK')"`

Expected: Output showing all 6 nodes + `__start__` + `__end__`, plus `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/analysis_graph.py
git commit -m "feat(template): add HTML analysis subgraph with parallel fan-out/fan-in"
```

---

### Task 3: Create Content Quality Check Subgraph (Approach B)

**Files:**
- Create: `src/stream_reconnection_demo/agent/template/quality_graph.py`

- [ ] **Step 1: Create the quality check subgraph module**

Create `src/stream_reconnection_demo/agent/template/quality_graph.py` with:

```python
"""Content quality check subgraph — Approach B (manual ainvoke).

This subgraph checks the email template's text content for spelling,
tone consistency, and CTA effectiveness in a linear pipeline.

Invoked manually via ``ainvoke()`` inside a wrapper node in the parent
graph. Events from this subgraph are NOT expected to appear in the
parent's ``astream_events()`` output — this is the control case for
testing subgraph event visibility.
"""

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from stream_reconnection_demo.agent.template.state import QualityCheckState


QUALITY_MODEL = "claude-sonnet-4-20250514"


SPELLING_PROMPT = """\
You are a professional proofreader. Check the following email template \
content for spelling, grammar, and punctuation errors.

## Template
Subject: {subject}
Preview text: {preview_text}

Section contents:
{section_contents}

## Instructions
Identify all errors and provide corrections. If the content is clean, \
say so. Be concise — list errors as bullet points with corrections.
"""

TONE_PROMPT = """\
You are a brand communication specialist. Analyze the tone consistency \
of this email template across all sections.

## Template
Subject: {subject}

Section contents:
{section_contents}

## Current spelling report
{spelling_report}

## Instructions
Evaluate:
- Is the tone consistent across header, body, CTA, and footer?
- Is the tone appropriate for the subject matter?
- Are there any jarring shifts in formality or style?

Be concise — provide a brief assessment with specific examples if issues exist.
"""

CTA_PROMPT = """\
You are a conversion optimization specialist. Evaluate the \
call-to-action (CTA) elements in this email template.

## Template
Subject: {subject}

Section contents:
{section_contents}

## Instructions
Evaluate:
- CTA clarity: Is the action obvious?
- CTA urgency: Does it motivate immediate action?
- CTA placement: Is it visible without scrolling?
- CTA count: Too many CTAs dilute effectiveness (ideal: 1 primary)

Be concise — provide a brief assessment with specific recommendations.
"""

AGGREGATE_PROMPT = """\
You are a content quality reviewer. Summarize the following quality \
check reports into a concise overall quality summary.

## Spelling Report
{spelling_report}

## Tone Report
{tone_report}

## CTA Report
{cta_report}

## Instructions
Write a 2-3 sentence summary of the template's content quality. \
Highlight the most important finding. Rate overall quality as: \
excellent, good, needs-work, or poor.
"""


def _extract_section_contents(template: dict) -> str:
    """Extract readable section contents from template dict."""
    sections = template.get("sections", [])
    if not sections:
        return template.get("html", "(no content)")
    parts = []
    for s in sections:
        s_type = s.get("type", "unknown")
        content = s.get("content", "")
        parts.append(f"[{s_type}] {content}")
    return "\n".join(parts)


def _build_check_spelling(llm: ChatAnthropic):
    async def check_spelling(
        state: QualityCheckState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        prompt = SPELLING_PROMPT.format(
            subject=template.get("subject", "(no subject)"),
            preview_text=template.get("preview_text", ""),
            section_contents=_extract_section_contents(template),
        )
        response = await llm.ainvoke(
            [SystemMessage(content="You are a professional proofreader."),
             HumanMessage(content=prompt)],
            config=config,
        )
        return {"spelling_report": response.content}

    return check_spelling


def _build_check_tone(llm: ChatAnthropic):
    async def check_tone(
        state: QualityCheckState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        prompt = TONE_PROMPT.format(
            subject=template.get("subject", "(no subject)"),
            section_contents=_extract_section_contents(template),
            spelling_report=state.get("spelling_report", "(not yet available)"),
        )
        response = await llm.ainvoke(
            [SystemMessage(content="You are a brand communication specialist."),
             HumanMessage(content=prompt)],
            config=config,
        )
        return {"tone_report": response.content}

    return check_tone


def _build_check_cta(llm: ChatAnthropic):
    async def check_cta(
        state: QualityCheckState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        prompt = CTA_PROMPT.format(
            subject=template.get("subject", "(no subject)"),
            section_contents=_extract_section_contents(template),
        )
        response = await llm.ainvoke(
            [SystemMessage(content="You are a conversion optimization specialist."),
             HumanMessage(content=prompt)],
            config=config,
        )
        return {"cta_report": response.content}

    return check_cta


def _build_aggregate_quality(llm: ChatAnthropic):
    async def aggregate_quality(
        state: QualityCheckState, config: RunnableConfig
    ) -> dict:
        prompt = AGGREGATE_PROMPT.format(
            spelling_report=state.get("spelling_report", "(none)"),
            tone_report=state.get("tone_report", "(none)"),
            cta_report=state.get("cta_report", "(none)"),
        )
        response = await llm.ainvoke(
            [SystemMessage(content="You are a content quality reviewer."),
             HumanMessage(content=prompt)],
            config=config,
        )
        return {"quality_summary": response.content}

    return aggregate_quality


def build_quality_graph(model: str = QUALITY_MODEL) -> StateGraph:
    """Build the content quality check subgraph (not compiled).

    Returns an uncompiled StateGraph. The parent graph's wrapper node
    compiles and invokes this via ``ainvoke()`` — it is NOT added
    as a native subgraph node.
    """
    llm = ChatAnthropic(model=model)

    graph = StateGraph(QualityCheckState)

    graph.add_node("check_spelling", _build_check_spelling(llm))
    graph.add_node("check_tone", _build_check_tone(llm))
    graph.add_node("check_cta", _build_check_cta(llm))
    graph.add_node("aggregate_quality", _build_aggregate_quality(llm))

    # Linear pipeline
    graph.add_edge(START, "check_spelling")
    graph.add_edge("check_spelling", "check_tone")
    graph.add_edge("check_tone", "check_cta")
    graph.add_edge("check_cta", "aggregate_quality")
    graph.add_edge("aggregate_quality", END)

    return graph
```

- [ ] **Step 2: Verify the module imports and graph builds correctly**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python3 -c "from stream_reconnection_demo.agent.template.quality_graph import build_quality_graph; g = build_quality_graph(); c = g.compile(); print('Nodes:', list(c.get_graph().nodes.keys())); print('OK')"`

Expected: Output showing 4 nodes + `__start__` + `__end__`, plus `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/quality_graph.py
git commit -m "feat(template): add content quality check subgraph (linear pipeline)"
```

---

### Task 4: Integrate Subgraphs into Parent Graph

**Files:**
- Modify: `src/stream_reconnection_demo/agent/template/graph.py`

- [ ] **Step 1: Update imports in graph.py**

Add the new imports at the top of `graph.py`, after the existing imports:

At the top, after `from stream_reconnection_demo.schemas.template import EmailTemplate`, add:

```python
from stream_reconnection_demo.agent.template.analysis_graph import build_analysis_graph
from stream_reconnection_demo.agent.template.quality_graph import build_quality_graph
```

- [ ] **Step 2: Add the quality check wrapper node builder**

Add a new function after `_build_modify_node` (after line 233) and before `_route_by_state`:

```python
def _build_quality_check_node(model: str):
    """Wrapper node that invokes the quality check subgraph via ainvoke().

    This is Approach B — the subgraph is NOT a native LangGraph subgraph.
    Its internal events are hidden from the parent's astream_events().
    """
    quality_graph = build_quality_graph(model=model).compile()

    async def quality_check_node(
        state: TemplateAgentState, config: RunnableConfig
    ) -> dict:
        template = state.get("template")
        if template is None:
            return {"quality_summary": "No template to check."}

        result = await quality_graph.ainvoke(
            {"template": template},
            config=config,
        )
        return {"quality_summary": result.get("quality_summary", "")}

    return quality_check_node
```

- [ ] **Step 3: Update build_template_graph to integrate both subgraphs**

Replace the `build_template_graph` function (lines 243-254) with:

```python
def build_template_graph(checkpointer=None, model="claude-sonnet-4-20250514"):
    """Build and compile the template generation/modification graph.

    Includes two subgraphs:
    - analyze_template: HTML analysis via native LangGraph composition (Approach A)
    - quality_check: Content quality via manual ainvoke wrapper (Approach B)
    """
    llm = ChatAnthropic(model=model)

    graph = StateGraph(TemplateAgentState, output=TemplateOutput)

    # Original nodes
    graph.add_node("generate_template", _build_generate_node(llm))
    graph.add_node("modify_template", _build_modify_node(llm))

    # Subgraph A: native composition — compiled graph as a node
    analysis_subgraph = build_analysis_graph(model=model).compile()
    graph.add_node("analyze_template", analysis_subgraph)

    # Subgraph B: wrapper node using ainvoke internally
    graph.add_node("quality_check", _build_quality_check_node(model=model))

    # Routing from START
    graph.add_conditional_edges(START, _route_by_state)

    # generate/modify → analyze → quality_check → END
    graph.add_edge("generate_template", "analyze_template")
    graph.add_edge("modify_template", "analyze_template")
    graph.add_edge("analyze_template", "quality_check")
    graph.add_edge("quality_check", END)

    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Verify the updated graph compiles and has correct structure**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python3 -c "
from stream_reconnection_demo.agent.template.graph import build_template_graph
g = build_template_graph()
nodes = list(g.get_graph().nodes.keys())
print('Parent nodes:', nodes)
print('OK')
"`

Expected: Nodes including `generate_template`, `modify_template`, `analyze_template`, `quality_check`, `__start__`, `__end__`. The `analyze_template` node should be a compiled subgraph.

- [ ] **Step 5: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/graph.py
git commit -m "feat(template): integrate analysis and quality check subgraphs into parent graph"
```

---

### Task 5: Enable stream_subgraphs in Routes

**Files:**
- Modify: `src/stream_reconnection_demo/agent/template/routes.py`

- [ ] **Step 1: Add stream_subgraphs to forwarded_props**

In `routes.py`, find the `RunAgentInput` construction (line 151-159). Change the `forwarded_props` from `{}` to `{"stream_subgraphs": True}`:

Replace:
```python
        forwarded_props={},
```

With:
```python
        forwarded_props={"stream_subgraphs": True},
```

- [ ] **Step 2: Add logging to EventAdapter for subgraph event observation**

In `src/stream_reconnection_demo/core/event_adapter.py`, add temporary debug logging to observe all events coming from the agent. In the `stream_events` method, after line 56 (`async for event_obj in agent.run(input_data):`), add a log line.

Replace:
```python
        async for event_obj in agent.run(input_data):
            # --- Custom event translation ---------------------------------
```

With:
```python
        async for event_obj in agent.run(input_data):
            logger.debug(
                "EventAdapter raw event: type=%s name=%s",
                getattr(event_obj, "type", "?"),
                getattr(event_obj, "name", getattr(event_obj, "step_name", "?")),
            )
            # --- Custom event translation ---------------------------------
```

- [ ] **Step 3: Verify routes.py imports still work**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python3 -c "from stream_reconnection_demo.agent.template.routes import router; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/stream_reconnection_demo/agent/template/routes.py src/stream_reconnection_demo/core/event_adapter.py
git commit -m "feat(template): enable stream_subgraphs and add debug logging for event observation"
```

---

### Task 6: Test Subgraph Event Streaming

**Files:** No files to create — this is a testing/observation task.

- [ ] **Step 1: Start the server**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && LOG_LEVEL=DEBUG python3 -m uvicorn stream_reconnection_demo.main:app --reload --port 8000`

Start in background if needed.

- [ ] **Step 2: Send a test request with stream_subgraphs=True (current config)**

Run:
```bash
curl -N -X POST http://localhost:8000/api/v1/template \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Create a simple welcome email for a SaaS product launch"}],
    "state": null,
    "metadata": {"requestType": "chat"},
    "thread_id": "test-subgraph-1",
    "run_id": "run-subgraph-1"
  }' 2>/dev/null | head -100
```

Observe the SSE events. Look for:
- Events from `analyze_subject`, `analyze_colors`, `analyze_typography`, `analyze_structure` (Subgraph A — native)
- Events from `check_spelling`, `check_tone`, `check_cta`, `aggregate_quality` (Subgraph B — ainvoke)
- `STEP_STARTED` / `STEP_FINISHED` events with subgraph node names
- `TEXT_MESSAGE_*` events from subgraph LLM calls

Save the full output to a file for documentation:
```bash
curl -N -X POST http://localhost:8000/api/v1/template \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Create a simple welcome email for a SaaS product launch"}],
    "state": null,
    "metadata": {"requestType": "chat"},
    "thread_id": "test-subgraph-2",
    "run_id": "run-subgraph-2"
  }' 2>/dev/null > /tmp/subgraph-events-enabled.txt
```

- [ ] **Step 3: Test with stream_subgraphs=False**

Temporarily change `forwarded_props` in `routes.py` back to `{}`, restart server, and repeat the test:

```bash
curl -N -X POST http://localhost:8000/api/v1/template \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Create a simple welcome email for a SaaS product launch"}],
    "state": null,
    "metadata": {"requestType": "chat"},
    "thread_id": "test-subgraph-3",
    "run_id": "run-subgraph-3"
  }' 2>/dev/null > /tmp/subgraph-events-disabled.txt
```

- [ ] **Step 4: Compare results and document findings**

Compare the two output files:
```bash
# Count event types in each
echo "=== stream_subgraphs=True ===" && grep -o '"type":"[^"]*"' /tmp/subgraph-events-enabled.txt | sort | uniq -c | sort -rn
echo "=== stream_subgraphs=False ===" && grep -o '"type":"[^"]*"' /tmp/subgraph-events-disabled.txt | sort | uniq -c | sort -rn
```

Document which events appeared from which subgraph nodes. The key findings to record:
1. Does Subgraph A (native) emit `STEP_STARTED/FINISHED` for its internal nodes?
2. Does Subgraph A emit `TEXT_MESSAGE_*` for its internal LLM calls?
3. Does Subgraph B (ainvoke) emit any internal events?
4. Does `stream_subgraphs=False` suppress Subgraph A's internal events?

- [ ] **Step 5: Restore stream_subgraphs=True and commit any test artifacts**

Ensure `forwarded_props={"stream_subgraphs": True}` is set in `routes.py`.

```bash
git add -A
git commit -m "test(template): verify subgraph event streaming behavior"
```

---

### Task 7: Document Findings in Walkthrough

**Files:**
- Modify: `ag-ui-langgraph-walkthrough.md`

- [ ] **Step 1: Read the current end of the walkthrough to find where to append**

Read the last section of `ag-ui-langgraph-walkthrough.md` to find the correct insertion point (after Section 8).

- [ ] **Step 2: Add Section 9 — Subgraph Event Streaming**

Append a new section after the existing content. The section should cover:

1. **9.1 LangGraph Subgraph Basics** — How subgraphs work in LangGraph (native composition via `add_node` with compiled graph vs manual `ainvoke`).

2. **9.2 The `stream_subgraphs` Forwarded Prop** — How ag-ui-langgraph passes `stream_subgraphs` from `RunAgentInput.forwarded_props` to `astream_events(subgraphs=True)`. Include the relevant code from `agent.py` lines 450-459.

3. **9.3 The Unused `is_subgraph_stream` Flag** — Document the detection code at lines 194-198 that computes `is_subgraph_stream` but never uses it. Discuss implications (events flow through unfiltered).

4. **9.4 No `stream_mode` Property** — Clarify the common misconception: ag-ui-langgraph uses `astream_events()` (LangChain callback events), not LangGraph's `.stream(stream_mode=...)`. The `stream_mode` parameter ("values", "updates", "custom", etc.) applies only to LangGraph's native `.stream()` / `.astream()` methods.

5. **9.5 Test Results** — Document the actual findings from Task 6:
   - Table comparing event counts with `stream_subgraphs=True` vs `False`
   - Which AG-UI event types appeared from Subgraph A (native) nodes
   - Whether Subgraph B (ainvoke) internal events were visible
   - Whether `stream_subgraphs=False` suppressed all subgraph events

6. **9.6 Fan-Out/Fan-In Pattern** — Document how the parallel analysis nodes work with the `Annotated[list, add]` reducer for fan-in.

7. **9.7 Recommendations** — When to use native composition vs manual ainvoke, and how `stream_subgraphs` affects event visibility.

- [ ] **Step 3: Update the Table of Contents**

Add entries for Section 9 and all subsections (9.1–9.7) to the TOC at the top of the walkthrough.

- [ ] **Step 4: Commit**

```bash
git add ag-ui-langgraph-walkthrough.md
git commit -m "docs: add Section 9 — subgraph event streaming findings to walkthrough"
```

---

### Task 8: Final Cleanup

**Files:**
- Modify: `src/stream_reconnection_demo/core/event_adapter.py` (remove debug logging if desired)

- [ ] **Step 1: Decide whether to keep debug logging**

The debug logging added in Task 5 Step 2 is at `DEBUG` level and won't appear in normal operation. If you want to keep it for future debugging, leave it. If you want to remove it, revert the change.

- [ ] **Step 2: Final verification — full server startup**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python3 -c "
from stream_reconnection_demo.agent.template.graph import build_template_graph
from ag_ui_langgraph import LangGraphAgent
g = build_template_graph()
agent = LangGraphAgent(name='template', graph=g)
print('Graph nodes:', list(g.get_graph().nodes.keys()))
print('Agent name:', agent.name)
print('All OK')
"`

Expected: All nodes listed, agent created successfully.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore(template): finalize subgraph integration and cleanup"
```
