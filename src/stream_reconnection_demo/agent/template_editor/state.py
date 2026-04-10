from operator import add
from typing import Annotated, NotRequired, TypedDict

from langgraph.graph.message import add_messages
from langgraph.prebuilt.chat_agent_executor import RemainingSteps

from stream_reconnection_demo.agent.template.state import AnalysisResult


def _last_template(existing: dict | None, new: dict | None) -> dict | None:
    """Reducer: accept the most recent template value.

    Required because parallel tool calls may each update 'template'
    in the same step.  The reducer prevents the InvalidUpdateError
    from LangGraph's LastValue channel.
    """
    return new if new is not None else existing


def _last_int(existing: int, new: int) -> int:
    """Reducer: take the higher version number."""
    return max(existing, new)


class TemplateEditorState(TypedDict):
    """State for the template editor agents (both FE-tools and BE-only)."""

    messages: Annotated[list, add_messages]
    remaining_steps: NotRequired[RemainingSteps]
    template: Annotated[dict | None, _last_template]
    version: Annotated[int, _last_int]
    error: str | None
    # Analysis results (populated when analyze_template tool is called)
    analyses: Annotated[list[AnalysisResult], add]
    overall_assessment: str | None
    needs_improvement: bool
    # Quality results (populated when quality_check tool is called)
    spelling_report: str | None
    tone_report: str | None
    cta_report: str | None
    quality_summary: str | None
