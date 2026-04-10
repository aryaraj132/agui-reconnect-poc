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
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
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
        allowed_step_names: set[str] | None = None,
        reasoning_step_names: set[str] | None = None,
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
        allowed_step_names:
            If provided, only STEP_STARTED/STEP_FINISHED events whose
            step_name is in this set will be emitted.  Subgraph-internal
            nodes are silently dropped.
        reasoning_step_names:
            Parent step names whose subgraph TEXT_MESSAGE events should be
            converted to REASONING events (single consolidated panel per
            step).  Subgraph TEXT under other parent steps passes through
            unchanged as regular messages.
        """
        in_subgraph = False
        current_parent_step: str | None = None
        reasoning_active = False
        reasoning_msg_id: str | None = None
        activity_msg_id = str(uuid.uuid4())

        async for event_obj in agent.run(input_data):
            logger.debug(
                "EventAdapter raw event: type=%s name=%s",
                getattr(event_obj, "type", "?"),
                getattr(event_obj, "name", getattr(event_obj, "step_name", "?")),
            )
            # --- Custom event translation ---------------------------------
            if event_obj.type == EventType.CUSTOM:
                async for translated in self._translate_custom(
                    event_obj, activity_msg_id
                ):
                    yield self._encoder.encode(translated)
                continue

            # --- MESSAGES_SNAPSHOT suppression -----------------------------
            # Suppress to prevent user message reappearing at bottom.
            # CopilotKit already has messages from individual TEXT_MESSAGE
            # events during live stream; catch-up emits its own snapshot.
            if event_obj.type == EventType.MESSAGES_SNAPSHOT:
                continue

            # --- STEP event filtering + subgraph tracking -----------------
            if allowed_step_names and event_obj.type in (
                EventType.STEP_STARTED, EventType.STEP_FINISHED
            ):
                step_name = getattr(event_obj, "step_name", "")
                if step_name in allowed_step_names:
                    # Close any active reasoning session when leaving subgraph
                    if reasoning_active:
                        yield self._encoder.encode(
                            ReasoningMessageEndEvent(message_id=reasoning_msg_id)
                        )
                        yield self._encoder.encode(
                            ReasoningEndEvent(message_id=reasoning_msg_id)
                        )
                        reasoning_active = False
                        reasoning_msg_id = None
                    in_subgraph = False
                    if event_obj.type == EventType.STEP_STARTED:
                        current_parent_step = step_name
                else:
                    if event_obj.type == EventType.STEP_STARTED:
                        in_subgraph = True
                    continue

            # --- TEXT_MESSAGE → REASONING (only for reasoning_step_names) --
            convert_to_reasoning = (
                in_subgraph
                and allowed_step_names
                and reasoning_step_names
                and current_parent_step in reasoning_step_names
            )

            if convert_to_reasoning:
                if event_obj.type == EventType.TEXT_MESSAGE_START:
                    if not reasoning_active:
                        reasoning_msg_id = str(uuid.uuid4())
                        yield self._encoder.encode(
                            ReasoningStartEvent(message_id=reasoning_msg_id)
                        )
                        yield self._encoder.encode(
                            ReasoningMessageStartEvent(
                                message_id=reasoning_msg_id, role="reasoning"
                            )
                        )
                        reasoning_active = True
                    else:
                        # Separator between analysis outputs in same panel
                        yield self._encoder.encode(
                            ReasoningMessageContentEvent(
                                message_id=reasoning_msg_id, delta="\n---\n"
                            )
                        )
                    continue
                if event_obj.type == EventType.TEXT_MESSAGE_CONTENT:
                    delta = getattr(event_obj, "delta", "")
                    yield self._encoder.encode(
                        ReasoningMessageContentEvent(
                            message_id=reasoning_msg_id, delta=delta
                        )
                    )
                    continue
                if event_obj.type == EventType.TEXT_MESSAGE_END:
                    # Don't close session — more subgraph nodes may follow.
                    # Session closes when parent step ends (allowed STEP event).
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

    async def _translate_custom(self, event_obj, activity_msg_id: str | None = None):
        """Translate CUSTOM events to proper AG-UI event types."""
        name = getattr(event_obj, "name", "")
        data = getattr(event_obj, "value", {})

        if name == "activity_snapshot":
            yield ActivitySnapshotEvent(
                type=EventType.ACTIVITY_SNAPSHOT,
                message_id=activity_msg_id or str(uuid.uuid4()),
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
