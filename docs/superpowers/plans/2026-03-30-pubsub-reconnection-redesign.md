# Redis Pub/Sub Reconnection Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Redis Streams with Pub/Sub + List buffering, consolidate to a single endpoint, and use LangGraph checkpointer for state persistence. Also create a `stateful-segment` variant that uses only checkpointer state (no Redis List) for catch-up.

**Architecture:** Agent runs as asyncio background task publishing AG-UI events to Redis Pub/Sub + List. Single `/api/v1/segment` endpoint handles new runs, reconnections, and regeneration by inferring intent from CopilotKit's request metadata. LangGraph MemorySaver checkpointer persists graph state for multi-turn conversations. A parallel `/api/v1/stateful-segment` endpoint demonstrates the same flow but relies solely on checkpointer state for catch-up (no Redis List), with Redis Pub/Sub for live events only.

**Tech Stack:** FastAPI, LangGraph (MemorySaver), Redis (Pub/Sub + Lists), AG-UI protocol, CopilotKit (React), Next.js

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `src/stream_reconnection_demo/core/pubsub.py` | Redis Pub/Sub manager: subscribe, buffer messages, deduplicate by sequence number, stream events. Also handles Redis List persistence (RPUSH/LRANGE) and run tracking keys (active_run, run_status). |
| `src/stream_reconnection_demo/core/agent_runner.py` | Starts agent as asyncio background task. Wraps the LangGraph pipeline execution, publishes each AG-UI event to both Pub/Sub and List, manages run lifecycle (start/complete/error). |
| `src/stream_reconnection_demo/agent/stateful_segment/routes.py` | POST /api/v1/stateful-segment — same as segment routes but catch-up uses only checkpointer state (no Redis List). |
| `src/stream_reconnection_demo/agent/stateful_segment/__init__.py` | Package init. |
| `src/stream_reconnection_demo/agent/stateful_segment/state.py` | Symlink/copy of segment state (same TypedDict). |
| `frontend/src/pages/StatefulSegmentPage.tsx` | Stateful-segment page — same UI as segment but hitting /api/v1/stateful-segment. |
| `frontend-next/app/stateful-segment/page.tsx` | Next.js stateful-segment page. |

### Modified Files

| File | What Changes |
|------|-------------|
| `src/stream_reconnection_demo/agent/segment/graph.py` | Add MemorySaver checkpointer to `build_segment_graph()` and `graph.compile(checkpointer=...)`. Accept and pass `thread_id` config. |
| `src/stream_reconnection_demo/agent/segment/routes.py` | Complete rewrite. Single endpoint with intent detection (Chat vs Connect). Delegates to `agent_runner` for new runs, to `pubsub` for reconnection/catch-up. Remove all Guards, remove middleware stack. |
| `src/stream_reconnection_demo/core/middleware.py` | Remove `RedisStreamMiddleware`. Keep `LoggingMiddleware` and `_parse_sse_event` (used by pubsub). Remove `HistoryMiddleware` and `CapabilityFilterMiddleware`. |
| `src/stream_reconnection_demo/core/events.py` | No structural changes. Keep as-is. |
| `src/stream_reconnection_demo/main.py` | Remove reconnect/threads router imports. Initialize `RedisPubSubManager` instead of `RedisStreamManager`. |
| `frontend/src/App.tsx` | Remove `useRestoreThread` import and usage. Remove `ReconnectionBanner`. Simplify `SegmentPageContent`. |
| `frontend/src/hooks/useAgentThread.ts` | Minor: remove `isExistingThread` logic (CopilotKit handles reconnection). |
| `frontend-next/app/segment/page.tsx` | Remove `useRestoreThread` import and usage. Remove `ReconnectionBanner`. Simplify `SegmentPageContent`. |
| `frontend-next/app/api/copilotkit/segment/route.ts` | Keep as-is (already points to `/api/v1/segment`). |
| `frontend-next/hooks/useAgentThread.ts` | Same simplification as `frontend/`. |
| `README.md` | Update architecture, endpoints, flow diagrams. |

### Delete Files

| File | Reason |
|------|--------|
| `src/stream_reconnection_demo/core/redis_stream.py` | Replaced by `pubsub.py` + `agent_runner.py` |
| `src/stream_reconnection_demo/api/reconnect.py` | No separate reconnect endpoint |
| `src/stream_reconnection_demo/api/threads.py` | No separate threads endpoint |
| `frontend/src/hooks/useRestoreThread.ts` | CopilotKit handles SSE |
| `frontend/src/components/ReconnectionBanner.tsx` | No custom reconnection UI |
| `frontend/src/lib/sse.ts` | No custom SSE parsing |
| `frontend-next/hooks/useRestoreThread.ts` | Same as above |
| `frontend-next/components/ReconnectionBanner.tsx` | Same as above |

---

### Task 1: Create Redis Pub/Sub Manager (`core/pubsub.py`)

**Files:**
- Create: `src/stream_reconnection_demo/core/pubsub.py`

- [ ] **Step 1: Create the `RedisPubSubManager` class with connection setup**

```python
"""Redis Pub/Sub + List manager for AG-UI event streaming and persistence.

Handles:
- Publishing events to Pub/Sub channels and persisting to Lists
- Subscribing to channels with buffering for catch-up deduplication
- Run tracking via active_run and run_status keys
- Event replay from Lists for reconnecting clients
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Key TTL in seconds
KEY_TTL = 3600

# Sentinel event types
STREAM_END = "STREAM_END"
STREAM_ERROR = "STREAM_ERROR"


class RedisPubSubManager:
    """Manages Redis Pub/Sub channels and Lists for AG-UI event streaming."""

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis = aioredis.from_url(
            redis_url, decode_responses=True, encoding="utf-8"
        )

    # -- key helpers ----------------------------------------------------------

    def _channel_key(self, thread_id: str, run_id: str) -> str:
        return f"agent:{thread_id}:{run_id}"

    def _events_key(self, thread_id: str, run_id: str) -> str:
        return f"events:{thread_id}:{run_id}"

    def _active_run_key(self, thread_id: str) -> str:
        return f"active_run:{thread_id}"

    def _run_status_key(self, thread_id: str, run_id: str) -> str:
        return f"run_status:{thread_id}:{run_id}"

    # -- run lifecycle --------------------------------------------------------

    async def start_run(self, thread_id: str, run_id: str) -> None:
        """Register a new active run for a thread."""
        await self._redis.set(
            self._active_run_key(thread_id), run_id, ex=KEY_TTL
        )
        await self._redis.set(
            self._run_status_key(thread_id, run_id), "running", ex=KEY_TTL
        )
        logger.info("Started run %s for thread %s", run_id, thread_id)

    async def complete_run(self, thread_id: str, run_id: str) -> None:
        """Mark run as completed, clear active_run, publish sentinel."""
        await self._redis.set(
            self._run_status_key(thread_id, run_id), "completed", ex=KEY_TTL
        )
        await self._redis.delete(self._active_run_key(thread_id))
        # Publish sentinel so live subscribers know to stop
        await self.publish_event(thread_id, run_id, STREAM_END)
        logger.info("Completed run %s for thread %s", run_id, thread_id)

    async def error_run(
        self, thread_id: str, run_id: str, error: str = ""
    ) -> None:
        """Mark run as errored, clear active_run, publish sentinel."""
        await self._redis.set(
            self._run_status_key(thread_id, run_id), "error", ex=KEY_TTL
        )
        await self._redis.delete(self._active_run_key(thread_id))
        await self.publish_event(thread_id, run_id, STREAM_ERROR)
        logger.info(
            "Error in run %s for thread %s: %s", run_id, thread_id, error
        )

    # -- publish + persist ----------------------------------------------------

    async def publish_event(
        self, thread_id: str, run_id: str, event_data: str
    ) -> int:
        """Persist event to List and publish to Pub/Sub channel.

        Returns the sequence number (1-based, from RPUSH).
        """
        events_key = self._events_key(thread_id, run_id)
        channel_key = self._channel_key(thread_id, run_id)

        # RPUSH returns the new list length = sequence number
        seq = await self._redis.rpush(events_key, event_data)
        await self._redis.expire(events_key, KEY_TTL)

        # Publish with sequence number for deduplication
        message = json.dumps({"seq": seq, "event": event_data})
        await self._redis.publish(channel_key, message)

        return seq

    # -- query ----------------------------------------------------------------

    async def get_active_run(self, thread_id: str) -> str | None:
        """Return the active run_id for a thread, or None."""
        return await self._redis.get(self._active_run_key(thread_id))

    async def get_run_status(
        self, thread_id: str, run_id: str
    ) -> str | None:
        """Return run status: 'running', 'completed', 'error', or None."""
        return await self._redis.get(self._run_status_key(thread_id, run_id))

    # -- catch-up (List read) -------------------------------------------------

    async def read_events(
        self, thread_id: str, run_id: str
    ) -> list[str]:
        """Read all persisted events from the List (LRANGE 0 -1).

        Returns list of event SSE strings in order.
        """
        events_key = self._events_key(thread_id, run_id)
        return await self._redis.lrange(events_key, 0, -1)

    async def get_event_count(self, thread_id: str, run_id: str) -> int:
        """Return the number of persisted events."""
        events_key = self._events_key(thread_id, run_id)
        return await self._redis.llen(events_key)

    # -- subscribe + deduplicate ----------------------------------------------

    async def subscribe_and_stream(
        self, thread_id: str, run_id: str, last_seq: int = 0
    ) -> AsyncIterator[str]:
        """Subscribe to Pub/Sub channel, yield events with seq > last_seq.

        Skips events already seen during catch-up (deduplication).
        Stops when STREAM_END or STREAM_ERROR sentinel is received.
        """
        channel_key = self._channel_key(thread_id, run_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel_key)

        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=5.0
                )
                if message is None:
                    # Timeout — check if run is still active
                    status = await self.get_run_status(thread_id, run_id)
                    if status in ("completed", "error"):
                        return
                    continue

                if message["type"] != "message":
                    continue

                try:
                    parsed = json.loads(message["data"])
                    seq = parsed.get("seq", 0)
                    event_data = parsed.get("event", "")
                except (json.JSONDecodeError, TypeError):
                    continue

                # Sentinel check
                if event_data in (STREAM_END, STREAM_ERROR):
                    return

                # Deduplication: skip events already seen during catch-up
                if seq <= last_seq:
                    continue

                yield event_data
        finally:
            await pubsub.unsubscribe(channel_key)
            await pubsub.aclose()

    async def catch_up_and_follow(
        self, thread_id: str, run_id: str
    ) -> AsyncIterator[str]:
        """Subscribe first, read List, yield catch-up, then yield live.

        Implements the race-condition-safe pattern:
        1. Subscribe to Pub/Sub (start buffering)
        2. Read all events from List (catch-up)
        3. Yield catch-up events
        4. Yield live events from Pub/Sub, skipping duplicates (seq <= last_seq)
        """
        channel_key = self._channel_key(thread_id, run_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel_key)

        try:
            # Step 2: Read all persisted events
            events = await self.read_events(thread_id, run_id)
            last_seq = len(events)

            # Step 3: Yield catch-up events
            for event_data in events:
                if event_data in (STREAM_END, STREAM_ERROR):
                    return
                yield event_data

            # Check if run already completed during catch-up
            status = await self.get_run_status(thread_id, run_id)
            if status in ("completed", "error"):
                return

            # Step 4: Yield live events, deduplicating by seq
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=5.0
                )
                if message is None:
                    status = await self.get_run_status(thread_id, run_id)
                    if status in ("completed", "error"):
                        return
                    continue

                if message["type"] != "message":
                    continue

                try:
                    parsed = json.loads(message["data"])
                    seq = parsed.get("seq", 0)
                    event_data = parsed.get("event", "")
                except (json.JSONDecodeError, TypeError):
                    continue

                if event_data in (STREAM_END, STREAM_ERROR):
                    return

                if seq <= last_seq:
                    continue

                yield event_data
        finally:
            await pubsub.unsubscribe(channel_key)
            await pubsub.aclose()

    # -- cleanup --------------------------------------------------------------

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self._redis.aclose()
```

- [ ] **Step 2: Verify the file was created correctly**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.core.pubsub import RedisPubSubManager; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/core/pubsub.py
git commit -m "feat: add Redis Pub/Sub manager with catch-up deduplication"
```

---

### Task 2: Create Agent Runner (`core/agent_runner.py`)

**Files:**
- Create: `src/stream_reconnection_demo/core/agent_runner.py`

- [ ] **Step 1: Create the `AgentRunner` class**

```python
"""Background agent task runner for LangGraph pipelines.

Runs the agent as an asyncio background task, publishing each AG-UI event
to Redis Pub/Sub + List for persistence and live streaming.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator

from stream_reconnection_demo.core.events import EventEmitter
from stream_reconnection_demo.core.pubsub import RedisPubSubManager

logger = logging.getLogger(__name__)
emitter = EventEmitter()

# Registry of running tasks so we can check/cancel them
_running_tasks: dict[str, asyncio.Task] = {}


async def run_agent_background(
    pubsub: RedisPubSubManager,
    segment_graph: Any,
    thread_id: str,
    run_id: str,
    event_stream: AsyncIterator[str],
) -> None:
    """Execute the agent pipeline, publishing each event to Redis.

    This function is meant to be run as an asyncio background task.
    It iterates over the AG-UI event stream from the pipeline and
    publishes each event to both Redis Pub/Sub and the event List.
    """
    try:
        async for event_sse in event_stream:
            try:
                await pubsub.publish_event(thread_id, run_id, event_sse)
            except Exception:
                logger.warning(
                    "Failed to publish event for run %s", run_id
                )

        # Mark run as completed
        try:
            await pubsub.complete_run(thread_id, run_id)
        except Exception:
            logger.warning("Failed to mark run %s as completed", run_id)

    except Exception as e:
        logger.exception("Agent run %s failed: %s", run_id, e)
        try:
            await pubsub.error_run(thread_id, run_id, str(e))
        except Exception:
            logger.warning("Failed to mark run %s as errored", run_id)
    finally:
        _running_tasks.pop(run_id, None)


def start_agent_task(
    pubsub: RedisPubSubManager,
    segment_graph: Any,
    thread_id: str,
    run_id: str,
    event_stream: AsyncIterator[str],
) -> asyncio.Task:
    """Start the agent pipeline as a background asyncio task.

    Returns the Task object for tracking.
    """
    task = asyncio.create_task(
        run_agent_background(
            pubsub, segment_graph, thread_id, run_id, event_stream
        ),
        name=f"agent-{run_id}",
    )
    _running_tasks[run_id] = task
    return task


def is_agent_running(run_id: str) -> bool:
    """Check if an agent task is currently running in this process."""
    task = _running_tasks.get(run_id)
    return task is not None and not task.done()
```

- [ ] **Step 2: Verify the file was created correctly**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.core.agent_runner import start_agent_task, is_agent_running; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/core/agent_runner.py
git commit -m "feat: add background agent task runner with pub/sub publishing"
```

---

### Task 3: Add MemorySaver Checkpointer to Graph

**Files:**
- Modify: `src/stream_reconnection_demo/agent/segment/graph.py:324-348`

- [ ] **Step 1: Modify `build_segment_graph()` to accept and use MemorySaver checkpointer**

In `src/stream_reconnection_demo/agent/segment/graph.py`, add `MemorySaver` import and modify `build_segment_graph()`:

Change the import block (line 6) from:
```python
from langgraph.graph import END, START, StateGraph
```
to:
```python
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
```

Change the `build_segment_graph` function (lines 324-348) from:
```python
def build_segment_graph(model: str = "claude-sonnet-4-20250514"):
    """Build and compile the 8-node segment generation graph."""
    llm = ChatAnthropic(model=model)

    graph = StateGraph(SegmentAgentState)
    graph.add_node("analyze_requirements", analyze_requirements)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("validate_fields", validate_fields)
    graph.add_node("map_operators", map_operators)
    graph.add_node("generate_conditions", generate_conditions)
    graph.add_node("optimize_conditions", optimize_conditions)
    graph.add_node("estimate_scope", estimate_scope)
    graph.add_node("build_segment", _build_segment_node(llm))

    graph.add_edge(START, "analyze_requirements")
    graph.add_edge("analyze_requirements", "extract_entities")
    graph.add_edge("extract_entities", "validate_fields")
    graph.add_edge("validate_fields", "map_operators")
    graph.add_edge("map_operators", "generate_conditions")
    graph.add_edge("generate_conditions", "optimize_conditions")
    graph.add_edge("optimize_conditions", "estimate_scope")
    graph.add_edge("estimate_scope", "build_segment")
    graph.add_edge("build_segment", END)

    return graph.compile()
```

to:

```python
def build_segment_graph(
    model: str = "claude-sonnet-4-20250514",
    checkpointer: MemorySaver | None = None,
):
    """Build and compile the 8-node segment generation graph."""
    llm = ChatAnthropic(model=model)

    graph = StateGraph(SegmentAgentState)
    graph.add_node("analyze_requirements", analyze_requirements)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("validate_fields", validate_fields)
    graph.add_node("map_operators", map_operators)
    graph.add_node("generate_conditions", generate_conditions)
    graph.add_node("optimize_conditions", optimize_conditions)
    graph.add_node("estimate_scope", estimate_scope)
    graph.add_node("build_segment", _build_segment_node(llm))

    graph.add_edge(START, "analyze_requirements")
    graph.add_edge("analyze_requirements", "extract_entities")
    graph.add_edge("extract_entities", "validate_fields")
    graph.add_edge("validate_fields", "map_operators")
    graph.add_edge("map_operators", "generate_conditions")
    graph.add_edge("generate_conditions", "optimize_conditions")
    graph.add_edge("optimize_conditions", "estimate_scope")
    graph.add_edge("estimate_scope", "build_segment")
    graph.add_edge("build_segment", END)

    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 2: Verify import works**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from langgraph.checkpoint.memory import MemorySaver; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/segment/graph.py
git commit -m "feat: add MemorySaver checkpointer support to segment graph"
```

---

### Task 4: Simplify Middleware — Remove Redis Stream Middleware

**Files:**
- Modify: `src/stream_reconnection_demo/core/middleware.py:111-149`

- [ ] **Step 1: Remove `RedisStreamMiddleware`, `HistoryMiddleware`, and `CapabilityFilterMiddleware`**

Replace the entire contents of `src/stream_reconnection_demo/core/middleware.py` with:

```python
"""Middleware infrastructure for AG-UI event stream processing.

Provides composable async generator wrappers that transform an SSE event
stream.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


def _parse_sse_event(sse_str: str) -> dict[str, Any] | None:
    """Extract the JSON payload from an SSE-formatted string.

    Expected format: ``data: {json}\\n\\n``.  Returns ``None`` when the
    string cannot be parsed (e.g. keep-alive comments).
    """
    line = sse_str.strip()
    if not line.startswith("data: "):
        return None
    json_str = line[len("data: "):]
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None


class LoggingMiddleware:
    """Logs each event type via :func:`logging.info`, yields event unchanged."""

    async def apply(self, event_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        async for event in event_stream:
            parsed = _parse_sse_event(event)
            if parsed is not None:
                event_type = parsed.get("type", "UNKNOWN")
                logger.info("AG-UI event: %s", event_type)
            yield event
```

- [ ] **Step 2: Verify the module still imports cleanly**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.core.middleware import LoggingMiddleware, _parse_sse_event; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/core/middleware.py
git commit -m "refactor: simplify middleware, remove RedisStreamMiddleware"
```

---

### Task 5: Rewrite Routes — Single Endpoint with Intent Detection

**Files:**
- Modify: `src/stream_reconnection_demo/agent/segment/routes.py` (complete rewrite)

This is the core task. The single endpoint must handle Chat (new run / regenerate) and Connect (reconnect / catch-up) requests. **Important:** During implementation, verify the actual CopilotKit request metadata structure (fields like `requestType`, how messages are passed, etc.) by inspecting the request body logged from CopilotKit rather than assuming.

- [ ] **Step 1: Rewrite the routes file**

Replace the entire contents of `src/stream_reconnection_demo/agent/segment/routes.py` with:

```python
import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from stream_reconnection_demo.core.events import EventEmitter, extract_user_query, get_field
from stream_reconnection_demo.core.agent_runner import start_agent_task
from stream_reconnection_demo.core.middleware import LoggingMiddleware

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)

# Metadata for each node in the pipeline
NODE_META = {
    "analyze_requirements": {
        "index": 0,
        "progress": 0.10,
        "status": "analyzing",
        "title": "Analyzing Requirements",
        "details": "Parsing user query and extracting segmentation intent...",
        "reasoning": [
            "Parsing the natural language query for segmentation intent... ",
            "Identifying target audience characteristics and filters... ",
            "Mapping keywords to available segmentation fields... ",
        ],
    },
    "extract_entities": {
        "index": 1,
        "progress": 0.20,
        "status": "extracting",
        "title": "Extracting Entities",
        "details": "Identifying entity types (locations, behaviors, etc.)...",
        "reasoning": [
            "Scanning query for entity references... ",
            "Classifying entities into categories (location, behavioral, demographic)... ",
            "Building entity map for downstream processing... ",
        ],
    },
    "validate_fields": {
        "index": 2,
        "progress": 0.30,
        "status": "validating",
        "title": "Validating Fields",
        "details": "Checking entities against available field catalog...",
        "reasoning": [
            "Cross-referencing detected entities with the field catalog... ",
            "Verifying field availability and compatibility... ",
            "Resolving ambiguous field references... ",
        ],
    },
    "map_operators": {
        "index": 3,
        "progress": 0.45,
        "status": "mapping",
        "title": "Mapping Operators",
        "details": "Selecting appropriate operators for each field...",
        "reasoning": [
            "Analyzing field types to determine valid operators... ",
            "Matching user intent to operator semantics... ",
            "Assigning categorical, temporal, and numeric operators... ",
        ],
    },
    "generate_conditions": {
        "index": 4,
        "progress": 0.55,
        "status": "generating",
        "title": "Generating Conditions",
        "details": "Building draft condition structures...",
        "reasoning": [
            "Constructing condition objects from operator mappings... ",
            "Determining value ranges and thresholds from context... ",
            "Structuring conditions into logical groups... ",
        ],
    },
    "optimize_conditions": {
        "index": 5,
        "progress": 0.70,
        "status": "optimizing",
        "title": "Optimizing Conditions",
        "details": "Simplifying and deduplicating conditions...",
        "reasoning": [
            "Scanning for duplicate field conditions... ",
            "Merging overlapping ranges and redundant filters... ",
            "Optimizing logical grouping for evaluation efficiency... ",
        ],
    },
    "estimate_scope": {
        "index": 6,
        "progress": 0.85,
        "status": "estimating",
        "title": "Estimating Scope",
        "details": "Estimating audience size and reach...",
        "reasoning": [
            "Analyzing condition specificity for audience estimation... ",
            "Evaluating filter combination impact on reach... ",
            "Generating scope summary based on condition count and types... ",
        ],
    },
    "build_segment": {
        "index": 7,
        "progress": 0.95,
        "status": "building",
        "title": "Building Segment",
        "details": "Generating final segment definition with LLM...",
        "reasoning": [
            "Synthesizing all pre-analyzed context into a coherent segment... ",
            "Applying segmentation best practices and naming conventions... ",
            "Generating structured output with conditions and scope estimate... ",
        ],
    },
}

TOTAL_NODES = len(NODE_META)


async def run_segment_pipeline(
    segment_graph,
    query: str,
    thread_id: str,
    run_id: str,
) -> AsyncIterator[str]:
    """Run the 8-node segment pipeline and yield AG-UI SSE events.

    Uses the checkpointer thread_id config so LangGraph persists state.
    """
    message_id = str(uuid.uuid4())

    yield emitter.emit_run_started(thread_id, run_id)

    try:
        graph_input = {
            "messages": [HumanMessage(content=query)],
            "segment": None,
            "error": None,
            "current_node": "",
            "requirements": None,
            "entities": [],
            "validated_fields": [],
            "operator_mappings": [],
            "conditions_draft": [],
            "optimized_conditions": [],
            "scope_estimate": None,
        }

        config = {"configurable": {"thread_id": thread_id}}
        result_segment = None

        async for chunk in segment_graph.astream(
            graph_input, config=config, stream_mode="updates"
        ):
            for node_name, node_output in chunk.items():
                if node_name not in NODE_META:
                    continue

                meta = NODE_META[node_name]

                yield emitter.emit_step_start(node_name)

                tool_call_id = str(uuid.uuid4())
                yield emitter.emit_tool_call_start(
                    tool_call_id, "update_progress_status", message_id
                )
                yield emitter.emit_tool_call_args(
                    tool_call_id,
                    json.dumps({
                        "status": meta["status"],
                        "node": node_name,
                        "node_index": meta["index"],
                        "total_nodes": TOTAL_NODES,
                    }),
                )
                yield emitter.emit_tool_call_end(tool_call_id)

                activity_id = str(uuid.uuid4())
                yield emitter.emit_activity_snapshot(
                    activity_id,
                    "processing",
                    {
                        "title": meta["title"],
                        "progress": meta["progress"],
                        "details": meta["details"],
                    },
                )

                reasoning_id = str(uuid.uuid4())
                yield emitter.emit_reasoning_start(reasoning_id)
                yield emitter.emit_reasoning_message_start(reasoning_id)
                for step in meta["reasoning"]:
                    yield emitter.emit_reasoning_content(reasoning_id, step)
                    await asyncio.sleep(0.05)
                yield emitter.emit_reasoning_message_end(reasoning_id)
                yield emitter.emit_reasoning_end(reasoning_id)

                delta_ops = []
                for field_name in (
                    "requirements", "entities", "validated_fields",
                    "operator_mappings", "conditions_draft",
                    "optimized_conditions", "scope_estimate",
                ):
                    val = node_output.get(field_name)
                    if val:
                        delta_ops.append({
                            "op": "add",
                            "path": f"/{field_name}",
                            "value": val,
                        })
                if delta_ops:
                    yield emitter.emit_state_delta(delta_ops)

                if node_name == "build_segment":
                    result_segment = node_output.get("segment")

                yield emitter.emit_step_finish(node_name)

        if result_segment is None:
            yield emitter.emit_run_error("Segment generation produced no result")
            return

        segment_dict = result_segment.model_dump()

        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()),
            "processing",
            {
                "title": "Segment Complete",
                "progress": 1.0,
                "details": f"Generated segment: {result_segment.name}",
            },
        )

        yield emitter.emit_state_snapshot(segment_dict)

        completion_tool_id = str(uuid.uuid4())
        yield emitter.emit_tool_call_start(
            completion_tool_id, "update_progress_status", message_id
        )
        yield emitter.emit_tool_call_args(
            completion_tool_id,
            json.dumps({
                "status": "completed",
                "node": "build_segment",
                "node_index": TOTAL_NODES - 1,
                "total_nodes": TOTAL_NODES,
            }),
        )
        yield emitter.emit_tool_call_end(completion_tool_id)

        summary = (
            f"Created segment: **{result_segment.name}**\n\n"
            f"{result_segment.description}"
        )
        yield emitter.emit_text_start(message_id, "assistant")
        yield emitter.emit_text_content(message_id, summary)
        yield emitter.emit_text_end(message_id)

    except Exception as e:
        logging.exception("Segment generation failed")
        yield emitter.emit_run_error(str(e))
        return

    yield emitter.emit_run_finished(thread_id, run_id)


@router.post("/segment")
async def generate_segment(request: Request):
    """Single endpoint for CopilotKit — handles new runs and reconnections.

    Intent detection based on CopilotKit request metadata:
    - Chat + new query: start agent background task, subscribe to pub/sub
    - Connect + active run: catch-up from List + bridge to live pub/sub
    - Connect + completed run: replay all events from List
    - Connect + no run: return checkpointer state
    """
    body = await request.json()

    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    messages = body.get("messages", [])
    query = extract_user_query(messages)

    # Detect request type from CopilotKit metadata
    # CopilotKit sends metadata.requestType = "chat" or "connect"
    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    segment_graph = request.app.state.segment_graph
    pubsub = request.app.state.pubsub

    logger.info(
        "Segment request: thread=%s type=%s query=%s",
        thread_id, request_type, query[:50] if query else "(empty)",
    )

    # --- CONNECT: Reconnection / catch-up ---
    if request_type == "connect":
        return await _handle_connect(pubsub, segment_graph, thread_id, run_id)

    # --- CHAT: New run or regeneration ---
    return await _handle_chat(
        pubsub, segment_graph, thread_id, run_id, query
    )


async def _handle_connect(pubsub, segment_graph, thread_id: str, run_id: str):
    """Handle a Connect request — reconnect to existing run or return state."""

    # Check for active run
    active_run_id = None
    try:
        active_run_id = await pubsub.get_active_run(thread_id)
    except Exception:
        logger.warning("Failed to check active run for thread %s", thread_id)

    if active_run_id:
        # Active run exists — catch-up + follow live
        logger.info(
            "Connect: active run %s for thread %s, catching up",
            active_run_id, thread_id,
        )

        async def reconnect_stream():
            try:
                async for event_sse in pubsub.catch_up_and_follow(
                    thread_id, active_run_id
                ):
                    yield event_sse
            except Exception:
                logger.exception("Reconnect stream failed for thread %s", thread_id)
                yield emitter.emit_run_error("Reconnection failed")

        return StreamingResponse(
            reconnect_stream(), media_type=emitter.content_type
        )

    # No active run — check if there's a completed run
    # Try to find the most recent run_id from checkpointer state
    try:
        checkpoint_state = await segment_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        checkpoint_state = None

    if checkpoint_state and checkpoint_state.values:
        # Reconstruct state from checkpointer
        logger.info("Connect: completed state from checkpointer for thread %s", thread_id)
        state = checkpoint_state.values
        segment = state.get("segment")

        async def completed_state_stream():
            yield emitter.emit_run_started(thread_id, run_id)
            if segment:
                yield emitter.emit_state_snapshot(segment.model_dump())
            # Reconstruct messages from checkpointer
            ck_messages = state.get("messages", [])
            if ck_messages:
                msg_dicts = []
                for msg in ck_messages:
                    if hasattr(msg, "content"):
                        role = "user" if hasattr(msg, "type") and msg.type == "human" else "assistant"
                        msg_dicts.append({"role": role, "content": msg.content})
                if msg_dicts:
                    yield emitter.emit_messages_snapshot(msg_dicts)
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            completed_state_stream(), media_type=emitter.content_type
        )

    # Nothing found — empty response
    logger.info("Connect: no state found for thread %s", thread_id)

    async def empty_stream():
        yield emitter.emit_run_started(thread_id, run_id)
        yield emitter.emit_run_finished(thread_id, run_id)

    return StreamingResponse(
        empty_stream(), media_type=emitter.content_type
    )


async def _handle_chat(pubsub, segment_graph, thread_id: str, run_id: str, query: str):
    """Handle a Chat request — start new agent run."""

    if not query.strip():
        # Empty query — return checkpointer state if available
        logger.info("Chat: empty query for thread %s", thread_id)
        try:
            checkpoint_state = await segment_graph.aget_state(
                {"configurable": {"thread_id": thread_id}}
            )
        except Exception:
            checkpoint_state = None

        async def empty_query_stream():
            yield emitter.emit_run_started(thread_id, run_id)
            if checkpoint_state and checkpoint_state.values:
                state = checkpoint_state.values
                segment = state.get("segment")
                if segment:
                    yield emitter.emit_state_snapshot(segment.model_dump())
                ck_messages = state.get("messages", [])
                if ck_messages:
                    msg_dicts = []
                    for msg in ck_messages:
                        if hasattr(msg, "content"):
                            role = "user" if hasattr(msg, "type") and msg.type == "human" else "assistant"
                            msg_dicts.append({"role": role, "content": msg.content})
                    if msg_dicts:
                        yield emitter.emit_messages_snapshot(msg_dicts)
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            empty_query_stream(), media_type=emitter.content_type
        )

    # Start the agent pipeline
    logger.info("Chat: starting new run %s for thread %s", run_id, thread_id)

    # Register run in Redis
    try:
        await pubsub.start_run(thread_id, run_id)
    except Exception:
        logger.warning("Failed to register run in Redis, proceeding anyway")

    # Create the event stream from the pipeline
    pipeline_stream = run_segment_pipeline(
        segment_graph, query, thread_id, run_id
    )

    # Start as background task
    start_agent_task(pubsub, segment_graph, thread_id, run_id, pipeline_stream)

    # Give the task a moment to start publishing
    await asyncio.sleep(0.1)

    # Subscribe to pub/sub and stream events to client
    async def live_stream():
        try:
            async for event_sse in pubsub.catch_up_and_follow(
                thread_id, run_id
            ):
                yield event_sse
        except Exception:
            logger.exception("Live stream failed for run %s", run_id)
            yield emitter.emit_run_error("Stream failed")

    return StreamingResponse(
        live_stream(), media_type=emitter.content_type
    )
```

- [ ] **Step 2: Verify the routes file imports correctly**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.agent.segment.routes import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/stream_reconnection_demo/agent/segment/routes.py
git commit -m "feat: rewrite routes with single endpoint, intent detection, pub/sub streaming"
```

---

### Task 6: Update `main.py` — Remove Old Routers, Use Pub/Sub Manager

**Files:**
- Modify: `src/stream_reconnection_demo/main.py`
- Delete: `src/stream_reconnection_demo/api/reconnect.py`
- Delete: `src/stream_reconnection_demo/api/threads.py`
- Delete: `src/stream_reconnection_demo/core/redis_stream.py`
- Delete: `src/stream_reconnection_demo/core/history.py`

- [ ] **Step 1: Rewrite `main.py`**

Replace the entire contents of `src/stream_reconnection_demo/main.py` with:

```python
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver

from stream_reconnection_demo.agent.segment.graph import build_segment_graph
from stream_reconnection_demo.agent.segment.routes import router as segment_router
from stream_reconnection_demo.core.pubsub import RedisPubSubManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build agent graph with MemorySaver checkpointer
    logger.info("Building segment graph with checkpointer...")
    checkpointer = MemorySaver()
    app.state.segment_graph = build_segment_graph(checkpointer=checkpointer)
    logger.info("Segment graph ready")

    # Initialize Redis Pub/Sub manager
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    logger.info("Connecting to Redis at %s", redis_url)
    try:
        app.state.pubsub = RedisPubSubManager(redis_url)
        logger.info("Redis Pub/Sub manager initialized")
    except Exception:
        logger.warning("Redis initialization failed, running without persistence")
        app.state.pubsub = RedisPubSubManager(redis_url)

    yield

    # Cleanup
    try:
        await app.state.pubsub.close()
        logger.info("Redis connection closed")
    except Exception:
        logger.warning("Redis cleanup failed")


app = FastAPI(
    title="AG-UI Stream Reconnection Demo",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single router — all reconnection logic handled within
app.include_router(segment_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "stream_reconnection_demo.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
```

- [ ] **Step 2: Delete the old files**

```bash
rm src/stream_reconnection_demo/api/reconnect.py
rm src/stream_reconnection_demo/api/threads.py
rm src/stream_reconnection_demo/core/redis_stream.py
rm src/stream_reconnection_demo/core/history.py
```

- [ ] **Step 3: Verify the app starts without import errors**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: consolidate to single endpoint, remove reconnect/threads/redis_stream/history"
```

---

### Task 7: Simplify React Frontend — Remove Reconnection Logic

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/hooks/useAgentThread.ts`
- Delete: `frontend/src/hooks/useRestoreThread.ts`
- Delete: `frontend/src/components/ReconnectionBanner.tsx`
- Delete: `frontend/src/lib/sse.ts`
- Delete: `frontend/src/hooks/useThreadHistory.ts`

- [ ] **Step 1: Simplify `useAgentThread.ts`**

Replace the contents of `frontend/src/hooks/useAgentThread.ts` with:

```typescript
import { useState, useRef, useEffect, useCallback } from "react";

export function useAgentThread() {
  const [threadFromUrl, setThreadFromUrl] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("thread");
  });

  const generatedId = useRef(crypto.randomUUID());
  const threadId = threadFromUrl || generatedId.current;

  const [mountedThreadId, setMountedThreadId] = useState(threadId);
  const [ready, setReady] = useState(true);

  useEffect(() => {
    if (threadId !== mountedThreadId) {
      setReady(false);
      const timer = setTimeout(() => {
        setMountedThreadId(threadId);
        setReady(true);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [threadId, mountedThreadId]);

  useEffect(() => {
    if (!threadFromUrl) {
      const pathname = window.location.pathname;
      window.history.replaceState(
        null,
        "",
        `${pathname}?thread=${generatedId.current}`
      );
      setThreadFromUrl(generatedId.current);
    }
  }, [threadFromUrl]);

  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      setThreadFromUrl(params.get("thread"));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const startNewThread = useCallback(() => {
    const newId = crypto.randomUUID();
    const pathname = window.location.pathname;
    window.history.pushState(null, "", `${pathname}?thread=${newId}`);
    setThreadFromUrl(newId);
  }, []);

  const switchToThread = useCallback((id: string) => {
    const pathname = window.location.pathname;
    window.history.pushState(null, "", `${pathname}?thread=${id}`);
    setThreadFromUrl(id);
  }, []);

  return {
    threadId: mountedThreadId,
    ready,
    startNewThread,
    switchToThread,
  };
}
```

- [ ] **Step 2: Simplify `App.tsx`**

Replace the contents of `frontend/src/App.tsx` with:

```tsx
import { useRef, useState } from "react";
import {
  CopilotKit,
  useCoAgentStateRender,
  useCoAgent,
  useCopilotAction,
} from "@copilotkit/react-core";
import {
  CopilotSidebar,
  RenderMessageProps,
  AssistantMessage as DefaultAssistantMessage,
  UserMessage as DefaultUserMessage,
  ImageRenderer as DefaultImageRenderer,
} from "@copilotkit/react-ui";
import { useAgentThread } from "@/hooks/useAgentThread";
import { Nav } from "@/components/Nav";
import { SegmentCard } from "@/components/SegmentCard";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { ProgressStatus } from "@/components/ProgressStatus";
import type { Segment } from "@/lib/types";

const COPILOT_RUNTIME_URL =
  process.env.COPILOT_RUNTIME_URL || "/copilotkit";

function CustomRenderMessage({
  message,
  messages,
  inProgress,
  index,
  isCurrentMessage,
  AssistantMessage = DefaultAssistantMessage,
  UserMessage = DefaultUserMessage,
  ImageRenderer = DefaultImageRenderer,
}: RenderMessageProps) {
  if (message.role === "reasoning" || message.role === "activity") {
    if (!inProgress) return null;
    const fromOldTurn = messages
      .slice(index + 1)
      .some((m) => m.role === "assistant" && m.content);
    if (fromOldTurn) return null;

    const hasNewerOfSameRole = messages
      .slice(index + 1)
      .some((m) => m.role === message.role);
    if (hasNewerOfSameRole) return null;

    if (message.role === "reasoning") {
      return <ReasoningPanel reasoning={message.content} defaultOpen />;
    }
    return (
      <ActivityIndicator
        activityType={(message as any).activityType ?? "processing"}
        content={message.content as any}
      />
    );
  }

  if (message.role === "user") {
    return (
      <UserMessage
        key={index}
        rawData={message}
        message={message}
        ImageRenderer={ImageRenderer}
      />
    );
  }

  if (message.role === "assistant") {
    return (
      <AssistantMessage
        key={index}
        rawData={message}
        message={message}
        isLoading={inProgress && isCurrentMessage && !message.content}
        isGenerating={inProgress && isCurrentMessage && !!message.content}
        isCurrentMessage={isCurrentMessage}
      />
    );
  }

  return null;
}

function SegmentPageContent() {
  useCoAgentStateRender({
    name: "default",
    render: ({ state }) =>
      state?.condition_groups ? <SegmentCard segment={state} /> : null,
  });

  const { state: segment } = useCoAgent<Segment>({
    name: "default",
  });

  const [progressStatus, setProgressStatus] = useState<{
    status: string;
    node: string;
    nodeIndex: number;
    totalNodes: number;
  } | null>(null);

  useCopilotAction({
    name: "update_progress_status",
    parameters: [
      { name: "status", type: "string", description: "Current status" },
      { name: "node", type: "string", description: "Current node name" },
      {
        name: "node_index",
        type: "number",
        description: "Current node index",
      },
      {
        name: "total_nodes",
        type: "number",
        description: "Total number of nodes",
      },
    ],
    handler: ({ status, node, node_index, total_nodes }) => {
      setProgressStatus({
        status,
        node,
        nodeIndex: node_index,
        totalNodes: total_nodes,
      });
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-lg space-y-6">
          {progressStatus && (
            <ProgressStatus
              status={progressStatus.status}
              node={progressStatus.node}
              nodeIndex={progressStatus.nodeIndex}
              totalNodes={progressStatus.totalNodes}
            />
          )}
          {segment?.condition_groups ? (
            <SegmentCard segment={segment} />
          ) : !progressStatus ? (
            <p className="text-sm text-gray-400 text-center">
              Describe your audience in the sidebar to generate a segment.
            </p>
          ) : null}
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const { threadId, ready, startNewThread, switchToThread } =
    useAgentThread();

  return (
    <>
      {ready ? (
        <CopilotKit
          key={threadId}
          runtimeUrl={COPILOT_RUNTIME_URL}
          threadId={threadId}
        >
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are a user segmentation assistant. The user will describe a target audience and you will generate a structured segment definition with conditions."
            labels={{
              title: "Segment Builder",
              initial:
                'Describe your target audience and I\'ll generate a structured segment.\n\nTry: **"Users from the US who signed up in the last 30 days and made a purchase"**',
            }}
          >
            <SegmentPageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}
```

- [ ] **Step 3: Delete reconnection-specific frontend files**

```bash
rm frontend/src/hooks/useRestoreThread.ts
rm frontend/src/components/ReconnectionBanner.tsx
rm frontend/src/lib/sse.ts
rm frontend/src/hooks/useThreadHistory.ts
rm frontend/src/components/AgentHistoryPanel.tsx
```

- [ ] **Step 4: Verify the frontend compiles**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npm run build`
Expected: Build succeeds without errors

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: simplify React frontend, remove custom reconnection logic"
```

---

### Task 8: Simplify Next.js Frontend — Remove Reconnection Logic

**Files:**
- Modify: `frontend-next/app/segment/page.tsx`
- Modify: `frontend-next/hooks/useAgentThread.ts`
- Delete: `frontend-next/hooks/useRestoreThread.ts`
- Delete: `frontend-next/components/ReconnectionBanner.tsx`
- Delete: `frontend-next/hooks/useThreadHistory.ts`
- Delete: `frontend-next/components/AgentHistoryPanel.tsx`

- [ ] **Step 1: Simplify `frontend-next/hooks/useAgentThread.ts`**

Replace with the same content as Task 7 Step 1 (the `useAgentThread.ts` code). The hook is identical for both frontends — it manages threadId in URL params.

- [ ] **Step 2: Simplify `frontend-next/app/segment/page.tsx`**

Replace the contents of `frontend-next/app/segment/page.tsx` with:

```tsx
"use client";

import { Suspense, useState } from "react";
import {
  CopilotKit,
  useCoAgentStateRender,
  useCoAgent,
  useCopilotAction,
} from "@copilotkit/react-core";
import {
  CopilotSidebar,
  RenderMessageProps,
  AssistantMessage as DefaultAssistantMessage,
  UserMessage as DefaultUserMessage,
  ImageRenderer as DefaultImageRenderer,
} from "@copilotkit/react-ui";
import { Nav } from "@/components/Nav";
import { SegmentCard } from "@/components/SegmentCard";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { useAgentThread } from "@/hooks/useAgentThread";
import { ProgressStatus } from "@/components/ProgressStatus";
import type { Segment } from "@/lib/types";

function CustomRenderMessage({
  message,
  messages,
  inProgress,
  index,
  isCurrentMessage,
  AssistantMessage = DefaultAssistantMessage,
  UserMessage = DefaultUserMessage,
  ImageRenderer = DefaultImageRenderer,
}: RenderMessageProps) {
  if (message.role === "reasoning" || message.role === "activity") {
    if (!inProgress) return null;
    const fromOldTurn = messages
      .slice(index + 1)
      .some((m) => m.role === "assistant" && m.content);
    if (fromOldTurn) return null;

    const hasNewerOfSameRole = messages
      .slice(index + 1)
      .some((m) => m.role === message.role);
    if (hasNewerOfSameRole) return null;

    if (message.role === "reasoning") {
      return <ReasoningPanel reasoning={message.content} defaultOpen />;
    }
    return (
      <ActivityIndicator
        activityType={(message as any).activityType ?? "processing"}
        content={message.content as any}
      />
    );
  }

  if (message.role === "user") {
    return (
      <UserMessage
        key={index}
        rawData={message}
        message={message}
        ImageRenderer={ImageRenderer}
      />
    );
  }

  if (message.role === "assistant") {
    return (
      <AssistantMessage
        key={index}
        rawData={message}
        message={message}
        isLoading={inProgress && isCurrentMessage && !message.content}
        isGenerating={inProgress && isCurrentMessage && !!message.content}
        isCurrentMessage={isCurrentMessage}
      />
    );
  }

  return null;
}

function SegmentPageContent() {
  useCoAgentStateRender({
    name: "default",
    render: ({ state }) =>
      state?.condition_groups ? <SegmentCard segment={state} /> : null,
  });

  const { state: segment } = useCoAgent<Segment>({
    name: "default",
  });

  const [progressStatus, setProgressStatus] = useState<{
    status: string;
    node: string;
    nodeIndex: number;
    totalNodes: number;
  } | null>(null);

  useCopilotAction({
    name: "update_progress_status",
    parameters: [
      { name: "status", type: "string", description: "Current status" },
      { name: "node", type: "string", description: "Current node name" },
      { name: "node_index", type: "number", description: "Current node index" },
      { name: "total_nodes", type: "number", description: "Total number of nodes" },
    ],
    handler: ({ status, node, node_index, total_nodes }) => {
      setProgressStatus({
        status,
        node,
        nodeIndex: node_index,
        totalNodes: total_nodes,
      });
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-lg space-y-6">
          {progressStatus && (
            <ProgressStatus
              status={progressStatus.status}
              node={progressStatus.node}
              nodeIndex={progressStatus.nodeIndex}
              totalNodes={progressStatus.totalNodes}
            />
          )}
          {segment?.condition_groups ? (
            <SegmentCard segment={segment} />
          ) : !progressStatus ? (
            <p className="text-sm text-gray-400 text-center">
              Describe your audience in the sidebar to generate a segment.
            </p>
          ) : null}
        </div>
      </main>
    </div>
  );
}

function SegmentPageInner() {
  const { threadId, ready, startNewThread, switchToThread } = useAgentThread();

  return (
    <>
      {ready ? (
        <CopilotKit
          key={threadId}
          runtimeUrl="/api/copilotkit/segment"
          threadId={threadId}
        >
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are a user segmentation assistant. The user will describe a target audience and you will generate a structured segment definition with conditions."
            labels={{
              title: "Segment Builder",
              initial:
                'Describe your target audience and I\'ll generate a structured segment.\n\nTry: **"Users from the US who signed up in the last 30 days and made a purchase"**',
            }}
          >
            <SegmentPageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function SegmentPage() {
  return (
    <Suspense>
      <SegmentPageInner />
    </Suspense>
  );
}
```

- [ ] **Step 3: Delete reconnection-specific frontend-next files**

```bash
rm frontend-next/hooks/useRestoreThread.ts
rm frontend-next/components/ReconnectionBanner.tsx
rm frontend-next/hooks/useThreadHistory.ts
rm frontend-next/components/AgentHistoryPanel.tsx
```

- [ ] **Step 4: Verify the Next.js frontend compiles**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend-next && npm run build`
Expected: Build succeeds without errors

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: simplify Next.js frontend, remove custom reconnection logic"
```

---

### Task 9: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite README with new architecture**

Replace the entire contents of `README.md` with:

```markdown
# AG-UI Stream Reconnection Demo

A proof-of-concept demonstrating **SSE stream reconnection** for AI agent pipelines using the [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui), Redis Pub/Sub, and LangGraph.

## Problem

In AG-UI applications, when a user reloads the browser during an active agent stream, the SSE connection drops but the backend continues processing. Events emitted after the disconnect are lost, leaving the frontend in an inconsistent state. Additionally, when an agent is started externally (by another agent), users opening the UI mid-execution need to catch up on events they missed.

## Solution

This demo implements a Redis Pub/Sub + List buffering reconnection mechanism:

1. **Agent runs as a background task**, publishing every AG-UI event to both Redis Pub/Sub (live streaming) and a Redis List (persistence)
2. **Single endpoint** handles new runs, reconnections, and mid-execution joins by inferring intent from CopilotKit's request metadata
3. **Race-condition-safe catch-up**: subscribe to Pub/Sub first, read List second, deduplicate by sequence number — zero events lost
4. **LangGraph MemorySaver** checkpointer persists graph state for multi-turn conversations

## Architecture

```
                    New Run (Chat)
  CopilotKit ─POST─> /api/v1/segment ──> Start Background Task
    ^                     |                      |
    |                     |               LangGraph Pipeline
    |                     |                      |
    |                     v                      v
    <──── SSE ──── Pub/Sub Subscribe <── Pub/Sub Publish + List RPUSH

                    Reconnection (Connect)
  CopilotKit ─POST─> /api/v1/segment
    ^                     |
    |                1. Subscribe Pub/Sub (buffer)
    |                2. LRANGE event List (catch-up)
    |                3. Yield catch-up events
    |                4. Yield live from Pub/Sub (dedup seq)
    <──── SSE ────────────┘
```

## Prerequisites

- Python 3.13+
- Node.js 18+
- Redis server
- `ANTHROPIC_API_KEY` environment variable

## Quick Start

```bash
# 1. Install dependencies
just prepare

# 2. Start Redis (requires podman or docker)
just redis

# 3. Start the FastAPI backend (new terminal)
just backend

# 4. Start the React frontend (new terminal)
just frontend
```

Open http://localhost:3000 and describe your target audience to generate a segment.

### Testing Reconnection

1. Start a segment generation (type a query, e.g., "Users from the US who signed up in the last 30 days")
2. While the 8-node pipeline is running (~80s), **reload the page**
3. CopilotKit automatically reconnects via the Connect flow
4. Events replay from Redis List (catch-up), then live follow via Pub/Sub
5. Pipeline completes normally

### Testing Mid-Execution Join

1. Start generation in one browser tab
2. Copy the URL (with `?thread=...` param) to another browser/tab
3. Open it — events catch up from Redis and bridge to live

## Project Structure

```
agui_stream_reconnection_demo/
├── src/stream_reconnection_demo/
│   ├── main.py                        # FastAPI app with Redis Pub/Sub + checkpointer
│   ├── core/
│   │   ├── events.py                  # AG-UI EventEmitter (SSE formatting)
│   │   ├── middleware.py              # LoggingMiddleware
│   │   ├── pubsub.py                  # Redis Pub/Sub + List manager
│   │   └── agent_runner.py            # Background agent task runner
│   ├── agent/segment/
│   │   ├── graph.py                   # 8-node LangGraph pipeline + checkpointer
│   │   ├── routes.py                  # POST /api/v1/segment (single endpoint)
│   │   └── state.py                   # SegmentAgentState TypedDict
│   └── schemas/
│       └── segment.py                 # Segment, Condition, ConditionGroup
│
├── frontend/                          # React + webpack (primary)
│   ├── src/
│   │   ├── App.tsx                    # Main app with CopilotKit
│   │   ├── components/
│   │   │   ├── SegmentCard.tsx        # Segment definition display
│   │   │   ├── ProgressStatus.tsx     # 8-step pipeline stepper
│   │   │   ├── ActivityIndicator.tsx  # Processing progress bar
│   │   │   ├── ReasoningPanel.tsx     # Chain-of-thought display
│   │   │   └── Nav.tsx                # Navigation header
│   │   ├── hooks/
│   │   │   └── useAgentThread.ts      # Thread ID + URL management
│   │   └── lib/
│   │       └── types.ts               # TypeScript interfaces
│   ├── webpack.config.js
│   └── package.json
│
├── frontend-next/                     # Next.js + CopilotKit (reference)
├── justfile                           # Task runner
└── pyproject.toml                     # Python dependencies
```

## How It Works

### Redis Key Structure

| Key | Type | Purpose | TTL |
|-----|------|---------|-----|
| `active_run:{thread_id}` | String | Maps thread to current active run_id | 1 hour |
| `run_status:{thread_id}:{run_id}` | String | `running` / `completed` / `error` | 1 hour |
| `events:{thread_id}:{run_id}` | List | Event buffer for catch-up (RPUSH/LRANGE) | 1 hour |
| `agent:{thread_id}:{run_id}` | Pub/Sub | Live event streaming channel | N/A |

### Intent Detection

The single endpoint infers what to do from CopilotKit's request:

| Scenario | requestType | Action |
|----------|-------------|--------|
| New query | Chat | Start background agent task, subscribe pub/sub |
| Reload / new browser | Connect | Catch-up from List + bridge to live pub/sub |
| Mid-execution join | Connect | Same as reload |
| Completed run reload | Connect | Replay from List or return checkpointer state |

### Race-Condition-Safe Catch-Up

To prevent event loss during the List-to-Pub/Sub transition:

1. **Subscribe** to Pub/Sub channel first (start buffering)
2. **Read** all events from Redis List (catch-up)
3. **Yield** catch-up events to client
4. **Yield** live events from Pub/Sub, skipping duplicates by sequence number

Each event gets a monotonic `seq` from `RPUSH` return value.

## Pipeline Nodes

| Node | Duration | Purpose |
|------|----------|---------|
| `analyze_requirements` | ~8s | Parse user query into structured requirements |
| `extract_entities` | ~8s | Identify entity types and fields |
| `validate_fields` | ~8s | Validate field names against schema |
| `map_operators` | ~8s | Map conditions to operators |
| `generate_conditions` | ~10s | Generate condition definitions |
| `optimize_conditions` | ~10s | Deduplicate and simplify conditions |
| `estimate_scope` | ~8s | Estimate audience size and reach |
| `build_segment` | LLM | Final segment generation with Claude |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/segment` | Single endpoint — new runs, reconnections, catch-up |
| GET | `/health` | Health check |

## Environment Variables

| Variable | Default | Used By |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | (required) | Backend — LLM calls |
| `REDIS_URL` | `redis://localhost:6379` | Backend — Pub/Sub + persistence |
| `BACKEND_URL` | `http://localhost:8000` | Frontend — API base URL |

## Frontend Variants

- **`frontend/`** (primary) — React + webpack with CopilotKit. Direct connection to backend.
- **`frontend-next/`** (reference) — Next.js + CopilotKit. Uses CopilotRuntime as proxy.

Both frontends are simplified — CopilotKit handles SSE connection lifecycle. No custom reconnection code needed.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README with new Pub/Sub architecture"
```

---

### Task 10: Integration Test — End-to-End Verification

**Files:** None (manual testing)

- [ ] **Step 1: Start Redis**

Run: `just redis` (or `docker run -d -p 6379:6379 redis:latest`)

- [ ] **Step 2: Start backend and verify startup**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && just backend`
Expected: "Segment graph ready", "Redis Pub/Sub manager initialized" in logs

- [ ] **Step 3: Start frontend and verify it loads**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && just frontend`
Expected: Webpack dev server starts, page loads at localhost:3000

- [ ] **Step 4: Test new generation flow**

1. Open http://localhost:3000
2. Type "Users from the US who signed up in the last 30 days"
3. Verify: progress status updates, reasoning panel shows, segment card appears at end

- [ ] **Step 5: Test reconnection flow**

1. Start a new generation
2. While pipeline is running (~30s in), reload the page
3. Verify: CopilotKit reconnects, events catch up from Redis, pipeline continues to completion

- [ ] **Step 6: Test mid-execution join**

1. Start generation in tab A
2. Copy URL to tab B (new browser context)
3. Verify: tab B catches up and shows live progress

- [ ] **Step 7: Test completed run reload**

1. Complete a full generation
2. Reload the page
3. Verify: segment state restored from checkpointer

- [ ] **Step 8: Log actual CopilotKit request metadata**

During testing, inspect backend logs to verify the actual `requestType` values CopilotKit sends. Adjust intent detection logic in routes.py if the field names or values differ from assumptions.

---

### Task 11: Create Stateful-Segment Backend — Checkpointer-Only Catch-Up

**Files:**
- Create: `src/stream_reconnection_demo/agent/stateful_segment/__init__.py`
- Create: `src/stream_reconnection_demo/agent/stateful_segment/routes.py`
- Modify: `src/stream_reconnection_demo/main.py` (add router)

This is a copy of the segment endpoint with one key difference: **no Redis List for event persistence**. Catch-up relies solely on the LangGraph checkpointer state. Redis Pub/Sub is used only for live event streaming.

**Edge case — missed events:** When a user connects mid-execution, events published to Pub/Sub before the subscription started are lost (Pub/Sub is fire-and-forget). Without the Redis List, these events cannot be replayed. The mitigation:
1. Subscribe to Pub/Sub FIRST (same pattern as segment)
2. Read checkpointer state to reconstruct what's happened (which nodes completed, intermediate results)
3. Emit synthetic AG-UI events (STATE_SNAPSHOT, progress status) from checkpointer state
4. Then yield live events from Pub/Sub

Trade-off: User sees a "state jump" instead of individual step replay. Some in-progress node events may be missed. This is acceptable for demonstrating the checkpointer-only approach.

- [ ] **Step 1: Create `__init__.py`**

Create an empty file at `src/stream_reconnection_demo/agent/stateful_segment/__init__.py`.

- [ ] **Step 2: Create `routes.py` for stateful-segment**

Create `src/stream_reconnection_demo/agent/stateful_segment/routes.py`:

```python
"""Stateful Segment endpoint — checkpointer-only catch-up (no Redis List).

Same agent pipeline as /api/v1/segment but catch-up on reconnect
uses only LangGraph MemorySaver checkpointer state. Redis Pub/Sub
is used for live event streaming only.
"""

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from stream_reconnection_demo.core.events import EventEmitter, extract_user_query, get_field
from stream_reconnection_demo.core.middleware import LoggingMiddleware

router = APIRouter(prefix="/api/v1")
emitter = EventEmitter()
logger = logging.getLogger(__name__)

# Same NODE_META as segment routes
NODE_META = {
    "analyze_requirements": {
        "index": 0, "progress": 0.10, "status": "analyzing",
        "title": "Analyzing Requirements",
        "details": "Parsing user query and extracting segmentation intent...",
        "reasoning": [
            "Parsing the natural language query for segmentation intent... ",
            "Identifying target audience characteristics and filters... ",
            "Mapping keywords to available segmentation fields... ",
        ],
    },
    "extract_entities": {
        "index": 1, "progress": 0.20, "status": "extracting",
        "title": "Extracting Entities",
        "details": "Identifying entity types (locations, behaviors, etc.)...",
        "reasoning": [
            "Scanning query for entity references... ",
            "Classifying entities into categories (location, behavioral, demographic)... ",
            "Building entity map for downstream processing... ",
        ],
    },
    "validate_fields": {
        "index": 2, "progress": 0.30, "status": "validating",
        "title": "Validating Fields",
        "details": "Checking entities against available field catalog...",
        "reasoning": [
            "Cross-referencing detected entities with the field catalog... ",
            "Verifying field availability and compatibility... ",
            "Resolving ambiguous field references... ",
        ],
    },
    "map_operators": {
        "index": 3, "progress": 0.45, "status": "mapping",
        "title": "Mapping Operators",
        "details": "Selecting appropriate operators for each field...",
        "reasoning": [
            "Analyzing field types to determine valid operators... ",
            "Matching user intent to operator semantics... ",
            "Assigning categorical, temporal, and numeric operators... ",
        ],
    },
    "generate_conditions": {
        "index": 4, "progress": 0.55, "status": "generating",
        "title": "Generating Conditions",
        "details": "Building draft condition structures...",
        "reasoning": [
            "Constructing condition objects from operator mappings... ",
            "Determining value ranges and thresholds from context... ",
            "Structuring conditions into logical groups... ",
        ],
    },
    "optimize_conditions": {
        "index": 5, "progress": 0.70, "status": "optimizing",
        "title": "Optimizing Conditions",
        "details": "Simplifying and deduplicating conditions...",
        "reasoning": [
            "Scanning for duplicate field conditions... ",
            "Merging overlapping ranges and redundant filters... ",
            "Optimizing logical grouping for evaluation efficiency... ",
        ],
    },
    "estimate_scope": {
        "index": 6, "progress": 0.85, "status": "estimating",
        "title": "Estimating Scope",
        "details": "Estimating audience size and reach...",
        "reasoning": [
            "Analyzing condition specificity for audience estimation... ",
            "Evaluating filter combination impact on reach... ",
            "Generating scope summary based on condition count and types... ",
        ],
    },
    "build_segment": {
        "index": 7, "progress": 0.95, "status": "building",
        "title": "Building Segment",
        "details": "Generating final segment definition with LLM...",
        "reasoning": [
            "Synthesizing all pre-analyzed context into a coherent segment... ",
            "Applying segmentation best practices and naming conventions... ",
            "Generating structured output with conditions and scope estimate... ",
        ],
    },
}

TOTAL_NODES = len(NODE_META)

# Ordered list of nodes for reconstructing progress from checkpointer
NODE_ORDER = [
    "analyze_requirements", "extract_entities", "validate_fields",
    "map_operators", "generate_conditions", "optimize_conditions",
    "estimate_scope", "build_segment",
]

# State fields that indicate a node has completed
NODE_STATE_FIELDS = {
    "analyze_requirements": "requirements",
    "extract_entities": "entities",
    "validate_fields": "validated_fields",
    "map_operators": "operator_mappings",
    "generate_conditions": "conditions_draft",
    "optimize_conditions": "optimized_conditions",
    "estimate_scope": "scope_estimate",
    "build_segment": "segment",
}


async def run_stateful_segment_pipeline(
    segment_graph,
    query: str,
    thread_id: str,
    run_id: str,
) -> AsyncIterator[str]:
    """Run the 8-node segment pipeline and yield AG-UI SSE events.

    Identical to segment pipeline but uses a separate graph instance
    with its own checkpointer namespace.
    """
    message_id = str(uuid.uuid4())

    yield emitter.emit_run_started(thread_id, run_id)

    try:
        graph_input = {
            "messages": [HumanMessage(content=query)],
            "segment": None,
            "error": None,
            "current_node": "",
            "requirements": None,
            "entities": [],
            "validated_fields": [],
            "operator_mappings": [],
            "conditions_draft": [],
            "optimized_conditions": [],
            "scope_estimate": None,
        }

        config = {"configurable": {"thread_id": thread_id}}
        result_segment = None

        async for chunk in segment_graph.astream(
            graph_input, config=config, stream_mode="updates"
        ):
            for node_name, node_output in chunk.items():
                if node_name not in NODE_META:
                    continue

                meta = NODE_META[node_name]

                yield emitter.emit_step_start(node_name)

                tool_call_id = str(uuid.uuid4())
                yield emitter.emit_tool_call_start(
                    tool_call_id, "update_progress_status", message_id
                )
                yield emitter.emit_tool_call_args(
                    tool_call_id,
                    json.dumps({
                        "status": meta["status"],
                        "node": node_name,
                        "node_index": meta["index"],
                        "total_nodes": TOTAL_NODES,
                    }),
                )
                yield emitter.emit_tool_call_end(tool_call_id)

                activity_id = str(uuid.uuid4())
                yield emitter.emit_activity_snapshot(
                    activity_id, "processing",
                    {"title": meta["title"], "progress": meta["progress"], "details": meta["details"]},
                )

                reasoning_id = str(uuid.uuid4())
                yield emitter.emit_reasoning_start(reasoning_id)
                yield emitter.emit_reasoning_message_start(reasoning_id)
                for step in meta["reasoning"]:
                    yield emitter.emit_reasoning_content(reasoning_id, step)
                    await asyncio.sleep(0.05)
                yield emitter.emit_reasoning_message_end(reasoning_id)
                yield emitter.emit_reasoning_end(reasoning_id)

                delta_ops = []
                for field_name in (
                    "requirements", "entities", "validated_fields",
                    "operator_mappings", "conditions_draft",
                    "optimized_conditions", "scope_estimate",
                ):
                    val = node_output.get(field_name)
                    if val:
                        delta_ops.append({"op": "add", "path": f"/{field_name}", "value": val})
                if delta_ops:
                    yield emitter.emit_state_delta(delta_ops)

                if node_name == "build_segment":
                    result_segment = node_output.get("segment")

                yield emitter.emit_step_finish(node_name)

        if result_segment is None:
            yield emitter.emit_run_error("Segment generation produced no result")
            return

        segment_dict = result_segment.model_dump()

        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()), "processing",
            {"title": "Segment Complete", "progress": 1.0, "details": f"Generated segment: {result_segment.name}"},
        )
        yield emitter.emit_state_snapshot(segment_dict)

        completion_tool_id = str(uuid.uuid4())
        yield emitter.emit_tool_call_start(completion_tool_id, "update_progress_status", message_id)
        yield emitter.emit_tool_call_args(
            completion_tool_id,
            json.dumps({"status": "completed", "node": "build_segment", "node_index": TOTAL_NODES - 1, "total_nodes": TOTAL_NODES}),
        )
        yield emitter.emit_tool_call_end(completion_tool_id)

        summary = f"Created segment: **{result_segment.name}**\n\n{result_segment.description}"
        yield emitter.emit_text_start(message_id, "assistant")
        yield emitter.emit_text_content(message_id, summary)
        yield emitter.emit_text_end(message_id)

    except Exception as e:
        logging.exception("Stateful segment generation failed")
        yield emitter.emit_run_error(str(e))
        return

    yield emitter.emit_run_finished(thread_id, run_id)


def _reconstruct_progress_from_state(state: dict) -> tuple[str | None, int]:
    """Determine the last completed node from checkpointer state.

    Returns (last_completed_node, completed_count).
    """
    last_completed = None
    completed_count = 0
    for node_name in NODE_ORDER:
        field = NODE_STATE_FIELDS.get(node_name)
        if field and state.get(field):
            last_completed = node_name
            completed_count += 1
        else:
            break
    return last_completed, completed_count


async def _emit_synthetic_catchup(
    state: dict, thread_id: str, run_id: str
) -> AsyncIterator[str]:
    """Emit synthetic AG-UI events from checkpointer state for catch-up.

    Reconstructs progress status and state deltas from stored state
    so the frontend can show where the pipeline is.
    """
    message_id = str(uuid.uuid4())
    yield emitter.emit_run_started(thread_id, run_id)

    # Reconstruct messages
    ck_messages = state.get("messages", [])
    if ck_messages:
        msg_dicts = []
        for msg in ck_messages:
            if hasattr(msg, "content"):
                role = "user" if hasattr(msg, "type") and msg.type == "human" else "assistant"
                msg_dicts.append({"role": role, "content": msg.content})
        if msg_dicts:
            yield emitter.emit_messages_snapshot(msg_dicts)

    # Emit synthetic progress for completed nodes
    last_node, completed_count = _reconstruct_progress_from_state(state)
    if last_node:
        meta = NODE_META[last_node]
        tool_call_id = str(uuid.uuid4())
        yield emitter.emit_tool_call_start(tool_call_id, "update_progress_status", message_id)
        yield emitter.emit_tool_call_args(
            tool_call_id,
            json.dumps({
                "status": meta["status"],
                "node": last_node,
                "node_index": meta["index"],
                "total_nodes": TOTAL_NODES,
            }),
        )
        yield emitter.emit_tool_call_end(tool_call_id)

        yield emitter.emit_activity_snapshot(
            str(uuid.uuid4()), "processing",
            {"title": meta["title"], "progress": meta["progress"], "details": f"Completed {completed_count}/{TOTAL_NODES} steps"},
        )

    # Emit state snapshot if segment exists
    segment = state.get("segment")
    if segment:
        if hasattr(segment, "model_dump"):
            yield emitter.emit_state_snapshot(segment.model_dump())
        elif isinstance(segment, dict):
            yield emitter.emit_state_snapshot(segment)


@router.post("/stateful-segment")
async def generate_stateful_segment(request: Request):
    """Single endpoint for stateful-segment — checkpointer-only catch-up.

    Same as /segment but reconnection uses checkpointer state instead
    of Redis List for catch-up. Redis Pub/Sub for live events only.
    """
    body = await request.json()

    thread_id = get_field(body, "thread_id", "threadId", str(uuid.uuid4()))
    run_id = get_field(body, "run_id", "runId", str(uuid.uuid4()))
    messages = body.get("messages", [])
    query = extract_user_query(messages)

    metadata = body.get("metadata", {})
    request_type = metadata.get("requestType", "chat")

    segment_graph = request.app.state.stateful_segment_graph
    pubsub = request.app.state.pubsub

    logger.info(
        "Stateful-segment request: thread=%s type=%s query=%s",
        thread_id, request_type, query[:50] if query else "(empty)",
    )

    if request_type == "connect":
        return await _handle_stateful_connect(
            pubsub, segment_graph, thread_id, run_id
        )

    return await _handle_stateful_chat(
        pubsub, segment_graph, thread_id, run_id, query
    )


async def _handle_stateful_connect(pubsub, segment_graph, thread_id: str, run_id: str):
    """Handle Connect — catch-up from checkpointer, then bridge to live Pub/Sub."""

    # Check for active run
    active_run_id = None
    try:
        active_run_id = await pubsub.get_active_run(thread_id)
    except Exception:
        logger.warning("Failed to check active run for thread %s", thread_id)

    if active_run_id:
        # Active run — subscribe to pub/sub first, then emit checkpointer state
        logger.info(
            "Stateful connect: active run %s, catching up from checkpointer",
            active_run_id,
        )

        async def reconnect_stream():
            # Step 1: Subscribe to Pub/Sub (buffer live events)
            channel_key = pubsub._channel_key(thread_id, active_run_id)
            ps = pubsub._redis.pubsub()
            await ps.subscribe(channel_key)

            try:
                # Step 2: Read checkpointer state
                try:
                    checkpoint_state = await segment_graph.aget_state(
                        {"configurable": {"thread_id": thread_id}}
                    )
                except Exception:
                    checkpoint_state = None

                # Step 3: Emit synthetic catch-up events from checkpointer
                if checkpoint_state and checkpoint_state.values:
                    async for event in _emit_synthetic_catchup(
                        checkpoint_state.values, thread_id, run_id
                    ):
                        yield event

                # Step 4: Yield live events from Pub/Sub (no dedup needed)
                while True:
                    message = await ps.get_message(
                        ignore_subscribe_messages=True, timeout=5.0
                    )
                    if message is None:
                        status = await pubsub.get_run_status(thread_id, active_run_id)
                        if status in ("completed", "error"):
                            # One final checkpointer read for final state
                            try:
                                final_state = await segment_graph.aget_state(
                                    {"configurable": {"thread_id": thread_id}}
                                )
                                if final_state and final_state.values:
                                    seg = final_state.values.get("segment")
                                    if seg and hasattr(seg, "model_dump"):
                                        yield emitter.emit_state_snapshot(seg.model_dump())
                            except Exception:
                                pass
                            yield emitter.emit_run_finished(thread_id, run_id)
                            return
                        continue

                    if message["type"] != "message":
                        continue

                    try:
                        import json as _json
                        parsed = _json.loads(message["data"])
                        event_data = parsed.get("event", "")
                    except (ValueError, TypeError):
                        continue

                    from stream_reconnection_demo.core.pubsub import STREAM_END, STREAM_ERROR
                    if event_data in (STREAM_END, STREAM_ERROR):
                        # Read final state from checkpointer
                        try:
                            final_state = await segment_graph.aget_state(
                                {"configurable": {"thread_id": thread_id}}
                            )
                            if final_state and final_state.values:
                                seg = final_state.values.get("segment")
                                if seg and hasattr(seg, "model_dump"):
                                    yield emitter.emit_state_snapshot(seg.model_dump())
                        except Exception:
                            pass
                        yield emitter.emit_run_finished(thread_id, run_id)
                        return

                    yield event_data
            finally:
                await ps.unsubscribe(channel_key)
                await ps.aclose()

        return StreamingResponse(
            reconnect_stream(), media_type=emitter.content_type
        )

    # No active run — check checkpointer for completed state
    try:
        checkpoint_state = await segment_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        checkpoint_state = None

    if checkpoint_state and checkpoint_state.values:
        logger.info("Stateful connect: completed state from checkpointer for thread %s", thread_id)

        async def completed_stream():
            async for event in _emit_synthetic_catchup(
                checkpoint_state.values, thread_id, run_id
            ):
                yield event
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            completed_stream(), media_type=emitter.content_type
        )

    # Nothing found
    logger.info("Stateful connect: no state for thread %s", thread_id)

    async def empty_stream():
        yield emitter.emit_run_started(thread_id, run_id)
        yield emitter.emit_run_finished(thread_id, run_id)

    return StreamingResponse(empty_stream(), media_type=emitter.content_type)


async def _handle_stateful_chat(pubsub, segment_graph, thread_id: str, run_id: str, query: str):
    """Handle Chat — start new run. Pub/Sub only (no List persistence)."""

    if not query.strip():
        logger.info("Stateful chat: empty query for thread %s", thread_id)
        try:
            checkpoint_state = await segment_graph.aget_state(
                {"configurable": {"thread_id": thread_id}}
            )
        except Exception:
            checkpoint_state = None

        async def empty_query_stream():
            if checkpoint_state and checkpoint_state.values:
                async for event in _emit_synthetic_catchup(
                    checkpoint_state.values, thread_id, run_id
                ):
                    yield event
            else:
                yield emitter.emit_run_started(thread_id, run_id)
            yield emitter.emit_run_finished(thread_id, run_id)

        return StreamingResponse(
            empty_query_stream(), media_type=emitter.content_type
        )

    logger.info("Stateful chat: new run %s for thread %s", run_id, thread_id)

    try:
        await pubsub.start_run(thread_id, run_id)
    except Exception:
        logger.warning("Failed to register run in Redis")

    # Start agent as background task — publish to Pub/Sub only (no List)
    pipeline_stream = run_stateful_segment_pipeline(
        segment_graph, query, thread_id, run_id
    )

    from stream_reconnection_demo.core.agent_runner import start_agent_task_pubsub_only
    start_agent_task_pubsub_only(pubsub, segment_graph, thread_id, run_id, pipeline_stream)

    await asyncio.sleep(0.1)

    # Subscribe and stream live events
    async def live_stream():
        try:
            async for event_sse in pubsub.subscribe_and_stream(thread_id, run_id, last_seq=0):
                yield event_sse
        except Exception:
            logger.exception("Stateful live stream failed for run %s", run_id)
            yield emitter.emit_run_error("Stream failed")

    return StreamingResponse(
        live_stream(), media_type=emitter.content_type
    )
```

- [ ] **Step 3: Add `start_agent_task_pubsub_only` to `agent_runner.py`**

Add to the end of `src/stream_reconnection_demo/core/agent_runner.py`:

```python
async def run_agent_pubsub_only(
    pubsub: RedisPubSubManager,
    segment_graph: Any,
    thread_id: str,
    run_id: str,
    event_stream: AsyncIterator[str],
) -> None:
    """Execute agent pipeline, publishing to Pub/Sub only (no List persistence).

    Used by the stateful-segment endpoint where catch-up relies on
    checkpointer state instead of event replay.
    """
    try:
        async for event_sse in event_stream:
            try:
                # Publish to Pub/Sub channel only — no RPUSH to List
                channel_key = pubsub._channel_key(thread_id, run_id)
                import json as _json
                seq = 0  # No sequence tracking without List
                message = _json.dumps({"seq": seq, "event": event_sse})
                await pubsub._redis.publish(channel_key, message)
            except Exception:
                logger.warning("Failed to publish event for run %s", run_id)

        try:
            await pubsub.complete_run(thread_id, run_id)
        except Exception:
            logger.warning("Failed to mark run %s as completed", run_id)

    except Exception as e:
        logger.exception("Agent run %s failed: %s", run_id, e)
        try:
            await pubsub.error_run(thread_id, run_id, str(e))
        except Exception:
            logger.warning("Failed to mark run %s as errored", run_id)
    finally:
        _running_tasks.pop(run_id, None)


def start_agent_task_pubsub_only(
    pubsub: RedisPubSubManager,
    segment_graph: Any,
    thread_id: str,
    run_id: str,
    event_stream: AsyncIterator[str],
) -> asyncio.Task:
    """Start agent as background task — Pub/Sub only, no List persistence."""
    task = asyncio.create_task(
        run_agent_pubsub_only(
            pubsub, segment_graph, thread_id, run_id, event_stream
        ),
        name=f"stateful-agent-{run_id}",
    )
    _running_tasks[run_id] = task
    return task
```

- [ ] **Step 4: Register the stateful-segment router in `main.py`**

Add to `src/stream_reconnection_demo/main.py`:

After the segment_router import, add:
```python
from stream_reconnection_demo.agent.stateful_segment.routes import router as stateful_segment_router
```

In the lifespan function, after building the segment graph, add:
```python
    # Build a separate graph for stateful-segment (own checkpointer namespace)
    stateful_checkpointer = MemorySaver()
    app.state.stateful_segment_graph = build_segment_graph(checkpointer=stateful_checkpointer)
    logger.info("Stateful segment graph ready")
```

After `app.include_router(segment_router)`, add:
```python
app.include_router(stateful_segment_router)
```

- [ ] **Step 5: Verify imports**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo && python -c "from stream_reconnection_demo.agent.stateful_segment.routes import router; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add stateful-segment endpoint with checkpointer-only catch-up"
```

---

### Task 12: Create Stateful-Segment Frontend Pages

**Files:**
- Create: `frontend/src/pages/StatefulSegmentPage.tsx`
- Modify: `frontend/src/App.tsx` (add routing or second page)
- Create: `frontend-next/app/stateful-segment/page.tsx`
- Create: `frontend-next/app/api/copilotkit/stateful-segment/route.ts`

- [ ] **Step 1: Create Next.js CopilotKit proxy route for stateful-segment**

Create `frontend-next/app/api/copilotkit/stateful-segment/route.ts`:

```typescript
import {
  CopilotRuntime,
  EmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const runtime = new CopilotRuntime({
  agents: {
    default: new LangGraphHttpAgent({
      url: `${BACKEND_URL}/api/v1/stateful-segment`,
      description: "Stateful segment generation agent (checkpointer-only)",
    }),
  },
});

export const POST = async (req: Request) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new EmptyAdapter(),
    endpoint: "/api/copilotkit/stateful-segment",
  });
  return handleRequest(req);
};
```

- [ ] **Step 2: Create Next.js stateful-segment page**

Create `frontend-next/app/stateful-segment/page.tsx` — this is a copy of `frontend-next/app/segment/page.tsx` with `runtimeUrl` changed to `/api/copilotkit/stateful-segment`:

```tsx
"use client";

import { Suspense, useState } from "react";
import {
  CopilotKit,
  useCoAgentStateRender,
  useCoAgent,
  useCopilotAction,
} from "@copilotkit/react-core";
import {
  CopilotSidebar,
  RenderMessageProps,
  AssistantMessage as DefaultAssistantMessage,
  UserMessage as DefaultUserMessage,
  ImageRenderer as DefaultImageRenderer,
} from "@copilotkit/react-ui";
import { Nav } from "@/components/Nav";
import { SegmentCard } from "@/components/SegmentCard";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { useAgentThread } from "@/hooks/useAgentThread";
import { ProgressStatus } from "@/components/ProgressStatus";
import type { Segment } from "@/lib/types";

function CustomRenderMessage({
  message, messages, inProgress, index, isCurrentMessage,
  AssistantMessage = DefaultAssistantMessage,
  UserMessage = DefaultUserMessage,
  ImageRenderer = DefaultImageRenderer,
}: RenderMessageProps) {
  if (message.role === "reasoning" || message.role === "activity") {
    if (!inProgress) return null;
    const fromOldTurn = messages.slice(index + 1).some((m) => m.role === "assistant" && m.content);
    if (fromOldTurn) return null;
    const hasNewerOfSameRole = messages.slice(index + 1).some((m) => m.role === message.role);
    if (hasNewerOfSameRole) return null;
    if (message.role === "reasoning") return <ReasoningPanel reasoning={message.content} defaultOpen />;
    return <ActivityIndicator activityType={(message as any).activityType ?? "processing"} content={message.content as any} />;
  }
  if (message.role === "user") return <UserMessage key={index} rawData={message} message={message} ImageRenderer={ImageRenderer} />;
  if (message.role === "assistant") {
    return <AssistantMessage key={index} rawData={message} message={message} isLoading={inProgress && isCurrentMessage && !message.content} isGenerating={inProgress && isCurrentMessage && !!message.content} isCurrentMessage={isCurrentMessage} />;
  }
  return null;
}

function SegmentPageContent() {
  useCoAgentStateRender({ name: "default", render: ({ state }) => state?.condition_groups ? <SegmentCard segment={state} /> : null });
  const { state: segment } = useCoAgent<Segment>({ name: "default" });
  const [progressStatus, setProgressStatus] = useState<{ status: string; node: string; nodeIndex: number; totalNodes: number } | null>(null);

  useCopilotAction({
    name: "update_progress_status",
    parameters: [
      { name: "status", type: "string", description: "Current status" },
      { name: "node", type: "string", description: "Current node name" },
      { name: "node_index", type: "number", description: "Current node index" },
      { name: "total_nodes", type: "number", description: "Total number of nodes" },
    ],
    handler: ({ status, node, node_index, total_nodes }) => {
      setProgressStatus({ status, node, nodeIndex: node_index, totalNodes: total_nodes });
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-lg space-y-6">
          {progressStatus && <ProgressStatus status={progressStatus.status} node={progressStatus.node} nodeIndex={progressStatus.nodeIndex} totalNodes={progressStatus.totalNodes} />}
          {segment?.condition_groups ? (
            <SegmentCard segment={segment} />
          ) : !progressStatus ? (
            <p className="text-sm text-gray-400 text-center">Describe your audience in the sidebar to generate a segment.</p>
          ) : null}
        </div>
      </main>
    </div>
  );
}

function StatefulSegmentPageInner() {
  const { threadId, ready } = useAgentThread();
  return (
    <>
      {ready ? (
        <CopilotKit key={threadId} runtimeUrl="/api/copilotkit/stateful-segment" threadId={threadId}>
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are a user segmentation assistant. The user will describe a target audience and you will generate a structured segment definition with conditions."
            labels={{
              title: "Segment Builder (Stateful)",
              initial: 'Describe your target audience and I\'ll generate a structured segment.\n\nTry: **"Users from the US who signed up in the last 30 days and made a purchase"**',
            }}
          >
            <SegmentPageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function StatefulSegmentPage() {
  return <Suspense><StatefulSegmentPageInner /></Suspense>;
}
```

- [ ] **Step 3: For the React+Webpack frontend, update `App.tsx` to support a simple path-based variant**

Add a URL check at the top of `App.tsx` to switch between segment and stateful-segment based on URL path. Alternatively, add a simple toggle or link in the Nav. The simplest approach: check `window.location.pathname` for `/stateful-segment` and use a different `COPILOT_RUNTIME_URL`.

In `frontend/src/App.tsx`, change the `COPILOT_RUNTIME_URL` constant:

```typescript
const isStatefulMode = window.location.pathname.includes("stateful");
const COPILOT_RUNTIME_URL = isStatefulMode
  ? (process.env.COPILOT_STATEFUL_RUNTIME_URL || "/copilotkit-stateful")
  : (process.env.COPILOT_RUNTIME_URL || "/copilotkit");
```

Also update the webpack dev server proxy to handle both paths (in `webpack.config.js` devServer.proxy section, add the stateful proxy pointing to `/api/v1/stateful-segment`).

- [ ] **Step 4: Verify both frontends compile**

Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend && npm run build`
Run: `cd /Users/araj/Documents/MIRepo/learning/agui_stream_reconnection_demo/frontend-next && npm run build`
Expected: Both succeed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add stateful-segment frontend pages for both React and Next.js"
```

---

### Task 13: Update README with Stateful-Segment Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add stateful-segment section to README**

Add a new section after the "How It Works" section:

```markdown
## Stateful-Segment Variant

The `/api/v1/stateful-segment` endpoint demonstrates an alternative approach where **catch-up relies solely on LangGraph checkpointer state** instead of Redis List event buffering.

### Key Differences

| Feature | `/api/v1/segment` | `/api/v1/stateful-segment` |
|---------|-------------------|---------------------------|
| Live streaming | Redis Pub/Sub | Redis Pub/Sub |
| Event persistence | Redis List (RPUSH) | None |
| Catch-up source | Redis List (LRANGE) | LangGraph checkpointer state |
| Catch-up fidelity | Full event replay | State snapshot (jump) |
| Missed events | None (List has all) | Possible during transition |

### Trade-Offs

- **Simpler Redis usage**: No List operations, only Pub/Sub + run tracking keys
- **State jump on reconnect**: Instead of replaying individual step events, the user sees the current state reconstructed from the checkpointer. No "fast-forward" animation.
- **Potential missed events**: Events published to Pub/Sub before the client subscribes are lost. The checkpointer state provides the last checkpoint, but in-progress node events may be missing.
```

Also update the API Endpoints table to include:

```markdown
| POST | `/api/v1/stateful-segment` | Same as segment but checkpointer-only catch-up |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add stateful-segment documentation to README"
```
