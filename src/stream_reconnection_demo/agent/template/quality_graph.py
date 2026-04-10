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
from langchain_core.callbacks import adispatch_custom_event
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
        await adispatch_custom_event(
            "activity_snapshot",
            {"title": "Checking spelling", "progress": 0.1, "details": "Running spell check..."},
            config=config,
        )
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
        await adispatch_custom_event(
            "activity_snapshot",
            {"title": "Spell check complete", "progress": 1.0, "details": "Spelling analysis done"},
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
        await adispatch_custom_event(
            "activity_snapshot",
            {"title": "Aggregating quality reports", "progress": 0.5, "details": "Combining all quality checks..."},
            config=config,
        )
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
