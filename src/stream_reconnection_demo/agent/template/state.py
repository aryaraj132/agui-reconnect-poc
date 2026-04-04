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
