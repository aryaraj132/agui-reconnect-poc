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
    # Subgraph B fields (mapped manually by wrapper):
    spelling_report: str | None
    tone_report: str | None
    cta_report: str | None
    quality_summary: str | None


class TemplateOutput(TypedDict):
    """Output schema — limits STATE_SNAPSHOT to these fields only."""
    template: dict | None
    quality_summary: str | None
