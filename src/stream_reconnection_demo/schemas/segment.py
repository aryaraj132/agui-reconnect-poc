from typing import Literal

from pydantic import BaseModel


class Condition(BaseModel):
    """A single filter condition for segmentation."""

    field: str
    operator: str
    value: str | int | float | list[str]


class ConditionGroup(BaseModel):
    """A group of conditions joined by a logical operator."""

    logical_operator: Literal["AND", "OR"]
    conditions: list[Condition]


class Segment(BaseModel):
    """A user segment definition with conditions."""

    name: str
    description: str
    condition_groups: list[ConditionGroup]
    estimated_scope: str | None = None
