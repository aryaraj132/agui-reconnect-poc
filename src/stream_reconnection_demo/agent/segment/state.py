from typing import TypedDict

from stream_reconnection_demo.schemas.segment import Segment


class SegmentAgentState(TypedDict):
    messages: list
    segment: Segment | None
    error: str | None
    # Multi-node pipeline tracking
    current_node: str
    requirements: str | None        # from analyze_requirements
    entities: list                   # from extract_entities
    validated_fields: list           # from validate_fields
    operator_mappings: list          # from map_operators
    conditions_draft: list           # from generate_conditions
    optimized_conditions: list       # from optimize_conditions
    scope_estimate: str | None       # from estimate_scope
