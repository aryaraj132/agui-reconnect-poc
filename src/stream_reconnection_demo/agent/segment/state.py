from typing import TypedDict

from stream_reconnection_demo.schemas.segment import Segment


class SegmentAgentState(TypedDict):
    messages: list
    segment: Segment | None
    error: str | None
    # Multi-node pipeline tracking
    current_node: str
    requirements: str | None
    validated_fields: list
    conditions_draft: list
