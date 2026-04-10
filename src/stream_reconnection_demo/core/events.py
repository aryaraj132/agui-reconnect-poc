"""Core event utilities for AG-UI protocol streaming.

Provides helper functions and an ``EventEmitter`` class that wraps
:class:`ag_ui.encoder.EventEncoder` with convenient methods for every
AG-UI event type.
"""

from __future__ import annotations

from typing import Any

import uuid

from ag_ui.core import (
    ActivitySnapshotEvent,
    AssistantMessage,
    CustomEvent,
    MessagesSnapshotEvent,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    UserMessage,
)
from ag_ui.encoder import EventEncoder


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def get_field(
    body: dict[str, Any],
    snake: str,
    camel: str,
    default: Any = None,
) -> Any:
    """Return a value from *body* trying the *snake* key first, then *camel*.

    Falls back to *default* when neither key is present.
    """
    if snake in body:
        return body[snake]
    if camel in body:
        return body[camel]
    return default


def extract_user_query(messages: list[dict[str, Any]]) -> str:
    """Return the text content of the last user message.

    Handles both plain string ``content`` and list-of-parts content
    (extracting only ``{"type": "text"}`` items).  Returns ``""`` when
    there are no user messages.
    """
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                part["text"]
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(parts)
    return ""


# ---------------------------------------------------------------------------
# EventEmitter
# ---------------------------------------------------------------------------


class EventEmitter:
    """Thin wrapper around :class:`EventEncoder` with typed emit helpers.

    Each ``emit_*`` method constructs the corresponding AG-UI event and
    returns the SSE-encoded string (``data: {json}\\n\\n``).
    """

    def __init__(self) -> None:
        self._encoder = EventEncoder()

    # -- properties ---------------------------------------------------------

    @property
    def content_type(self) -> str:
        """MIME type for the SSE response (``text/event-stream``)."""
        return self._encoder.get_content_type()

    # -- run lifecycle ------------------------------------------------------

    def emit_run_started(self, thread_id: str, run_id: str) -> str:
        return self._encoder.encode(RunStartedEvent(thread_id=thread_id, run_id=run_id))

    def emit_run_finished(self, thread_id: str, run_id: str) -> str:
        return self._encoder.encode(
            RunFinishedEvent(thread_id=thread_id, run_id=run_id)
        )

    def emit_run_error(self, message: str) -> str:
        return self._encoder.encode(RunErrorEvent(message=message))

    # -- steps --------------------------------------------------------------

    def emit_step_start(self, step_name: str) -> str:
        return self._encoder.encode(StepStartedEvent(step_name=step_name))

    def emit_step_finish(self, step_name: str) -> str:
        return self._encoder.encode(StepFinishedEvent(step_name=step_name))

    # -- text message streaming ---------------------------------------------

    def emit_text_start(self, message_id: str, role: str) -> str:
        return self._encoder.encode(
            TextMessageStartEvent(message_id=message_id, role=role)
        )

    def emit_text_content(self, message_id: str, delta: str) -> str:
        return self._encoder.encode(
            TextMessageContentEvent(message_id=message_id, delta=delta)
        )

    def emit_text_end(self, message_id: str) -> str:
        return self._encoder.encode(TextMessageEndEvent(message_id=message_id))

    # -- state --------------------------------------------------------------

    def emit_state_snapshot(self, snapshot: dict[str, Any]) -> str:
        return self._encoder.encode(StateSnapshotEvent(snapshot=snapshot))

    def emit_state_delta(self, delta: list[dict[str, Any]]) -> str:
        return self._encoder.encode(StateDeltaEvent(delta=delta))

    # -- tool calls ---------------------------------------------------------

    def emit_tool_call_start(
        self,
        tool_call_id: str,
        tool_call_name: str,
        parent_message_id: str | None = None,
    ) -> str:
        return self._encoder.encode(
            ToolCallStartEvent(
                tool_call_id=tool_call_id,
                tool_call_name=tool_call_name,
                parent_message_id=parent_message_id,
            )
        )

    def emit_tool_call_args(self, tool_call_id: str, delta: str) -> str:
        return self._encoder.encode(
            ToolCallArgsEvent(tool_call_id=tool_call_id, delta=delta)
        )

    def emit_tool_call_end(self, tool_call_id: str) -> str:
        return self._encoder.encode(ToolCallEndEvent(tool_call_id=tool_call_id))

    # -- activity -----------------------------------------------------------

    def emit_activity_snapshot(
        self,
        message_id: str,
        activity_type: str,
        content: Any,
        replace: bool = True,
    ) -> str:
        return self._encoder.encode(
            ActivitySnapshotEvent(
                message_id=message_id,
                activity_type=activity_type,
                content=content,
                replace=replace,
            )
        )

    # -- reasoning ----------------------------------------------------------

    def emit_reasoning_start(self, message_id: str) -> str:
        return self._encoder.encode(ReasoningStartEvent(message_id=message_id))

    def emit_reasoning_message_start(self, message_id: str) -> str:
        return self._encoder.encode(
            ReasoningMessageStartEvent(message_id=message_id, role="reasoning")
        )

    def emit_reasoning_content(self, message_id: str, delta: str) -> str:
        return self._encoder.encode(
            ReasoningMessageContentEvent(message_id=message_id, delta=delta)
        )

    def emit_reasoning_message_end(self, message_id: str) -> str:
        return self._encoder.encode(ReasoningMessageEndEvent(message_id=message_id))

    def emit_reasoning_end(self, message_id: str) -> str:
        return self._encoder.encode(ReasoningEndEvent(message_id=message_id))

    # -- custom & messages --------------------------------------------------

    @staticmethod
    def langchain_messages_to_agui(messages: list) -> list[dict[str, Any]]:
        """Convert LangChain messages to AG-UI format for MESSAGES_SNAPSHOT.

        Maps ``HumanMessage`` (type="human") → role="user" and
        ``AIMessage`` (type="ai") → role="assistant".
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            if not hasattr(msg, "type") or not hasattr(msg, "content"):
                continue
            # Skip tool messages — they're internal plumbing, not chat
            if msg.type in ("tool",):
                continue
            role = "user" if msg.type == "human" else "assistant"
            msg_id = getattr(msg, "id", None) or str(uuid.uuid4())
            content = msg.content
            # Anthropic AI messages with tool calls use list-of-blocks
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                    if not (isinstance(block, dict) and block.get("type") == "tool_use")
                ).strip()
            if content:
                result.append({"id": msg_id, "role": role, "content": content})
        return result

    def emit_custom(self, name: str, value: Any) -> str:
        return self._encoder.encode(CustomEvent(name=name, value=value))

    def emit_messages_snapshot(self, messages: list[dict[str, Any]]) -> str:
        """Emit a MESSAGES_SNAPSHOT event.

        Accepts plain dicts with ``role`` and ``content`` keys and converts
        them to AG-UI message model instances.
        """
        agui_messages = []
        for msg in messages:
            msg_id = msg.get("id", str(uuid.uuid4()))
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Anthropic messages may have structured content blocks
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                    if not (isinstance(block, dict) and block.get("type") == "tool_use")
                ).strip()
            if role == "user":
                agui_messages.append(UserMessage(id=msg_id, content=content))
            elif content:
                agui_messages.append(AssistantMessage(id=msg_id, content=content))
        return self._encoder.encode(MessagesSnapshotEvent(messages=agui_messages))
