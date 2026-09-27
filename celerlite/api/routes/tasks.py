"""Task management API routes."""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from celerlite.api.app import get_broker
from celerlite.broker.redis_broker import RedisBroker
from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.config import config
from celerlite.observability.metrics import metrics
from celerlite.persistence.database import get_session
from celerlite.persistence.repository import TaskRepository
from celerlite.scheduler.priority import Priority

router = APIRouter()


class SubmitTaskRequest(BaseModel):
    task_name: str
    args: list = []
    kwargs: dict = {}
    queue: str = "default"
    priority: int = 1
    eta: Optional[str] = None
    metadata: dict = {}
    max_retries: int = 3
    timeout: int = 300


class RevokeResponse(BaseModel):
    task_id: str
    status: str


@router.post("/submit")
async def submit_task(body: SubmitTaskRequest, broker: RedisBroker = Depends(get_broker)):
    """Submit a task to the queue."""
    message = TaskMessage(
        task_id=str(uuid.uuid4()),
        task_name=body.task_name,
        args=body.args,
        kwargs=body.kwargs,
        queue=body.queue,
        priority=body.priority,
        max_retries=body.max_retries,
        timeout=body.timeout,
        eta=body.eta,
        metadata=body.metadata,
    )
    raw = Serializer.serialize(message)
    await broker.enqueue(body.queue, raw, priority=body.priority)

    async with get_session() as session:
        repo = TaskRepository(session)
        await repo.create_task(message)

    await broker.publish_event({
        "event": "task_submitted",
        "task_id": message.task_id,
        "task_name": body.task_name,
        "queue": body.queue,
    })
    metrics.record_submitted()

    return {"task_id": message.task_id, "status": "PENDING", "queue": body.queue}


@router.get("/stats")
async def get_stats():
    """Return task count by status and throughput metrics."""
    async with get_session() as session:
        repo = TaskRepository(session)
        counts = await repo.get_counts_by_status()
        throughput = await repo.get_throughput()

    snapshot = metrics.get_snapshot()
    return {
        **counts,
        "throughput_per_sec": throughput,
        "avg_latency_ms": snapshot["avg_latency_ms"],
        "p99_latency_ms": snapshot["p99_latency_ms"],
    }


@router.get("/{task_id}")
async def get_task(task_id: str):
    """Get full task details."""
    async with get_session() as session:
        repo = TaskRepository(session)
        task = await repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "id": task.id,
        "task_name": task.task_name,
        "status": task.status,
        "queue": task.queue,
        "priority": task.priority,
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "args_json": task.args_json,
        "kwargs_json": task.kwargs_json,
        "result_json": task.result_json,
        "error_message": task.error_message,
        "error_traceback": task.error_traceback,
        "worker_id": task.worker_id,
        "timeout": task.timeout,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("/{task_id}/result")
async def get_task_result(task_id: str, broker: RedisBroker = Depends(get_broker)):
    """Get task result from Redis (fast path)."""
    raw = await broker.get_result(task_id)
    if raw is None:
        async with get_session() as session:
            repo = TaskRepository(session)
            task = await repo.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task_id": task_id, "status": task.status, "result": None}

    result = Serializer.deserialize_result(raw)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "completed_at": result.completed_at,
    }


@router.get("")
async def list_tasks(
    status: Optional[str] = Query(None),
    queue: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List tasks with optional filters."""
    async with get_session() as session:
        repo = TaskRepository(session)
        tasks = await repo.get_tasks(status=status, queue=queue, limit=limit, offset=offset)
    return [
        {
            "id": t.id,
            "task_name": t.task_name,
            "status": t.status,
            "queue": t.queue,
            "priority": t.priority,
            "retry_count": t.retry_count,
            "worker_id": t.worker_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in tasks
    ]


@router.post("/{task_id}/revoke")
async def revoke_task(task_id: str, broker: RedisBroker = Depends(get_broker)):
    """Mark a task as revoked."""
    await broker.mark_task_revoked(task_id)
    async with get_session() as session:
        repo = TaskRepository(session)
        await repo.update_status(task_id, "REVOKED")
    return {"task_id": task_id, "status": "REVOKED"}
