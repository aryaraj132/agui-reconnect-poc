"""HTML analysis subgraph — Approach A (native LangGraph composition).

This subgraph analyzes an email template's HTML across 4 dimensions
in parallel (fan-out/fan-in), synthesizes an overall assessment,
and optionally applies improvements.

When added to the parent graph via ``add_node("analyze_template", compiled_graph)``,
LangGraph treats it as a true subgraph with namespaced events.
"""

import json

from stream_reconnection_demo.core.llm import DEFAULT_MODEL, get_llm
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from stream_reconnection_demo.agent.template.state import (
    AnalysisResult,
    AnalysisSubgraphState,
)
from stream_reconnection_demo.schemas.template import EmailTemplate




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


def _build_analyze_subject(llm):
    async def analyze_subject(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        await adispatch_custom_event(
            "activity_snapshot",
            {"title": "Analyzing subject line", "progress": 0.1, "details": "Starting subject analysis..."},
            config=config,
        )
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
        await adispatch_custom_event(
            "activity_snapshot",
            {"title": "Subject analysis complete", "progress": 1.0, "details": f"Severity: {result['severity']}"},
            config=config,
        )
        return {"analyses": [result]}

    return analyze_subject


def _build_analyze_colors(llm):
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


def _build_analyze_typography(llm):
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


def _build_analyze_structure(llm):
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


def _build_overall_analysis(llm):
    async def overall_analysis(
        state: AnalysisSubgraphState, config: RunnableConfig
    ) -> dict:
        template = state.get("template") or {}
        analyses = state.get("analyses", [])
        analyses_json = json.dumps(analyses, indent=2)

        await adispatch_custom_event(
            "activity_snapshot",
            {"title": "Synthesizing analyses", "progress": 0.5, "details": f"Reviewing {len(analyses)} analyses..."},
            config=config,
        )

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
        needs = parsed.get("needs_improvement", False)
        await adispatch_custom_event(
            "activity_snapshot",
            {"title": "Overall analysis complete", "progress": 1.0, "details": f"Needs improvement: {needs}"},
            config=config,
        )
        return {
            "overall_assessment": parsed.get("overall_assessment", ""),
            "needs_improvement": needs,
        }

    return overall_analysis


def _route_after_overall(state: AnalysisSubgraphState) -> str:
    """Route to apply_improvements or END based on needs_improvement flag."""
    if state.get("needs_improvement", False):
        return "apply_improvements"
    return END


def _build_apply_improvements(llm):
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


def build_analysis_graph(model: str = DEFAULT_MODEL) -> StateGraph:
    """Build the HTML analysis subgraph (not compiled).

    Returns an uncompiled StateGraph so the parent can compile it
    as part of its own compilation, or it can be compiled standalone
    for testing.
    """
    llm = get_llm(model)

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
