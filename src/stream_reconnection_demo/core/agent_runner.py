"""Background agent task runner for LangGraph pipelines.

Runs the agent as an asyncio background task, publishing each AG-UI event
to Redis Pub/Sub + List for persistence and live streaming.
"""

from __future__ import annotations

import asyncio
import json
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
    seq_counter = 0
    try:
        async for event_sse in event_stream:
            try:
                # Publish to Pub/Sub channel only — no RPUSH to List
                channel_key = pubsub._channel_key(thread_id, run_id)
                seq_counter += 1
                message = json.dumps({"seq": seq_counter, "event": event_sse})
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
