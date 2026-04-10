"""Bridges LangGraphAgent.run() output to SSE strings.

Translates custom events into proper AG-UI event types, filters
intermediate STATE_SNAPSHOT events, and encodes everything via
EventEncoder for the agent_runner pipeline.
"""

from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator

from ag_ui.core import (
    ActivitySnapshotEvent,
    EventType,
    RunAgentInput,
    StateDeltaEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder
from ag_ui_langgraph import LangGraphAgent

logger = logging.getLogger(__name__)


class EventAdapter:
    """Adapts LangGraphAgent event objects to SSE strings.

    Yields ``str`` values in the same format as ``run_segment_pipeline()``
    so the existing ``agent_runner`` can consume them without changes.
    """

    def __init__(self) -> None:
        self._encoder = EventEncoder()

    async def stream_events(
        self,
        agent: LangGraphAgent,
        input_data: RunAgentInput,
        *,
        state_snapshot_key: str = "template",
    ) -> AsyncIterator[str]:
        """Run the agent and yield SSE-encoded event strings.

        Parameters
        ----------
        agent:
            The LangGraphAgent to execute.
        input_data:
            AG-UI input payload (thread_id, run_id, messages, state, etc.).
        state_snapshot_key:
            The key in STATE_SNAPSHOT to check. Intermediate snapshots
            where this key is ``None`` are suppressed.
        """
        async for event_obj in agent.run(input_data):
            logger.debug(
                "EventAdapter raw event: type=%s name=%s",
                getattr(event_obj, "type", "?"),
                getattr(event_obj, "name", getattr(event_obj, "step_name", "?")),
            )
            # --- Custom event translation ---------------------------------
            if event_obj.type == EventType.CUSTOM:
                async for translated in self._translate_custom(event_obj):
                    yield self._encoder.encode(translated)
                continue

            # --- STATE_SNAPSHOT filtering + extraction ----------------------
            # Extract just the state_snapshot_key value (e.g. "template")
            # from the full graph state so CopilotKit receives the domain
            # object directly, not the entire graph state.
            if event_obj.type == EventType.STATE_SNAPSHOT:
                snapshot = getattr(event_obj, "snapshot", None) or {}
                if isinstance(snapshot, dict):
                    extracted = snapshot.get(state_snapshot_key)
                    if extracted is None:
                        continue
                    event_obj = StateSnapshotEvent(
                        type=EventType.STATE_SNAPSHOT,
                        snapshot=extracted,
                    )

            # --- Inject empty state reset after RUN_STARTED ---------------
            if event_obj.type == EventType.RUN_STARTED:
                yield self._encoder.encode(event_obj)
                yield self._encoder.encode(
                    StateSnapshotEvent(
                        type=EventType.STATE_SNAPSHOT,
                        snapshot={},
                    )
                )
                continue

            yield self._encoder.encode(event_obj)

    async def _translate_custom(self, event_obj):
        """Translate CUSTOM events to proper AG-UI event types."""
        name = getattr(event_obj, "name", "")
        data = getattr(event_obj, "value", {})

        if name == "activity_snapshot":
            yield ActivitySnapshotEvent(
                type=EventType.ACTIVITY_SNAPSHOT,
                message_id=str(uuid.uuid4()),
                activity_type="processing",
                content=data,
            )

        elif name == "state_delta":
            ops = data.get("ops", []) if isinstance(data, dict) else []
            if ops:
                yield StateDeltaEvent(
                    type=EventType.STATE_DELTA,
                    delta=ops,
                )

        # Unknown custom events are silently dropped (not re-emitted as CUSTOM)
