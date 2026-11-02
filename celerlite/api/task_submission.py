"""Persist queue work before publishing it so fast workers cannot win a race."""

from typing import Any

from fastapi import HTTPException

from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.observability.logger import get_logger
from celerlite.observability.metrics import metrics
from celerlite.persistence import database
from celerlite.persistence.repository import TaskRepository

logger = get_logger(__name__)


async def enqueue_tracked_task(message: TaskMessage, broker: Any) -> None:
    """Save task history, enqueue the payload, and emit a best-effort event.

    The database row must commit before enqueueing: workers can reserve and
    finish small jobs immediately, so enqueue-first can leave a successful
    queue message represented as permanently pending in task history.
    """
    if broker is None:
        raise HTTPException(status_code=503, detail="Task broker is unavailable")

    async with database.get_session() as session:
        await TaskRepository(session).create_task(message)

    raw = Serializer.serialize(message)
    try:
        await broker.enqueue(message.queue, raw, priority=message.priority)
    except Exception as exc:
        try:
            async with database.get_session() as session:
                await TaskRepository(session).update_status(
                    message.task_id,
                    "FAILED",
                    error_message="The task could not be delivered to the queue.",
                )
        except Exception:
            logger.exception("task_enqueue_failure_status_write_failed", task_id=message.task_id)
        raise HTTPException(status_code=503, detail="Task queue is unavailable") from exc

    try:
        await broker.publish_event({
            "event": "task_submitted",
            "task_id": message.task_id,
            "task_name": message.task_name,
            "queue": message.queue,
        })
    except Exception:
        # Queue delivery already succeeded. Polling remains the source of truth
        # for the task state if the transient event channel is unavailable.
        logger.warning("task_submitted_event_unavailable", task_id=message.task_id)

    metrics.record_submitted()
