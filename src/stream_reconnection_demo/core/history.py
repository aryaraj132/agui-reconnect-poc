"""In-memory thread store for conversation persistence.

Provides a :class:`ThreadStore` that keeps all conversation data
(messages, events, state) indexed by ``thread_id``.  A module-level
singleton :data:`thread_store` is exported for use across the application.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class ThreadData(TypedDict):
    """Shape of a single thread's persisted data."""

    messages: list[dict[str, Any]]
    events: list[dict[str, Any]]
    state: dict[str, Any]
    agent_type: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# ThreadStore
# ---------------------------------------------------------------------------


class ThreadStore:
    """Simple in-memory store for conversation threads.

    All timestamps use UTC ISO-8601 format.
    """

    def __init__(self) -> None:
        self._threads: dict[str, ThreadData] = {}

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _require_thread(self, thread_id: str) -> ThreadData:
        """Return the thread or raise :class:`KeyError`."""
        try:
            return self._threads[thread_id]
        except KeyError:
            raise KeyError(f"Thread '{thread_id}' not found") from None

    # -- public API ---------------------------------------------------------

    def create_thread(self, thread_id: str, agent_type: str) -> ThreadData:
        """Create and return a new thread."""
        now = self._now()
        thread: ThreadData = {
            "messages": [],
            "events": [],
            "state": {},
            "agent_type": agent_type,
            "created_at": now,
            "updated_at": now,
        }
        self._threads[thread_id] = thread
        return thread

    def get_thread(self, thread_id: str) -> ThreadData | None:
        """Return the thread data, or ``None`` if not found."""
        return self._threads.get(thread_id)

    def list_threads(self, agent_type: str | None = None) -> list[dict[str, Any]]:
        """Return lightweight summaries, optionally filtered by *agent_type*."""
        results = []
        for tid, data in self._threads.items():
            if agent_type and data["agent_type"] != agent_type:
                continue
            first_message = ""
            for msg in data["messages"]:
                if msg.get("role") == "user":
                    first_message = msg.get("content", "")[:100]
                    break
            results.append({
                "id": tid,
                "agent_type": data["agent_type"],
                "message_count": len(data["messages"]),
                "first_message": first_message,
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
            })
        return results

    def add_message(self, thread_id: str, message: dict[str, Any]) -> None:
        """Append a message to the thread's history.

        Assigns a stable ``id`` if the message doesn't already have one.
        """
        thread = self._require_thread(thread_id)
        if "id" not in message:
            message = {**message, "id": str(uuid.uuid4())}
        thread["messages"].append(message)
        thread["updated_at"] = self._now()

    def add_event(self, thread_id: str, event: dict[str, Any]) -> None:
        """Append an event to the thread's event log."""
        thread = self._require_thread(thread_id)
        thread["events"].append(event)
        thread["updated_at"] = self._now()

    def update_state(self, thread_id: str, state: dict[str, Any]) -> None:
        """Merge *state* into the thread's current state."""
        thread = self._require_thread(thread_id)
        thread["state"].update(state)
        thread["updated_at"] = self._now()

    def get_or_create_thread(self, thread_id: str, agent_type: str) -> ThreadData:
        """Return the existing thread or create a new one (idempotent)."""
        existing = self.get_thread(thread_id)
        if existing is not None:
            return existing
        return self.create_thread(thread_id, agent_type)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

thread_store = ThreadStore()
