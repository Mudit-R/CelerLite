"""Dead Letter Queue management endpoints."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from celerlite.api.app import get_broker
from celerlite.broker.redis_broker import RedisBroker
from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.persistence.database import get_session
from celerlite.persistence.repository import DLQRepository, TaskRepository

router = APIRouter()


@router.get("")
async def list_dlq(limit: int = 50, offset: int = 0):
    async with get_session() as session:
        repo = DLQRepository(session)
        entries = await repo.get_entries(replayed=False, limit=limit, offset=offset)
    return [
        {
            "id": e.id,
            "task_id": e.task_id,
            "task_name": e.task_name,
            "error_message": e.error_message,
            "retry_count": e.retry_count,
            "original_queue": e.original_queue,
            "dead_lettered_at": e.dead_lettered_at.isoformat(),
            "replayed": e.replayed,
        }
        for e in entries
    ]


@router.get("/count")
async def dlq_count():
    async with get_session() as session:
        repo = DLQRepository(session)
        count = await repo.get_dlq_count(replayed=False)
    return {"count": count}


@router.post("/{entry_id}/replay")
async def replay_entry(entry_id: str, broker: RedisBroker = Depends(get_broker)):
    """Re-submit a DLQ task to its original queue with retry_count reset."""
    async with get_session() as session:
        dlq_repo = DLQRepository(session)
        entry = await dlq_repo.get_entry(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="DLQ entry not found")
        if entry.replayed:
            raise HTTPException(status_code=409, detail="Entry already replayed")

        # Rebuild task message
        message = TaskMessage(
            task_id=str(uuid.uuid4()),
            task_name=entry.task_name,
            args=json.loads(entry.args_json),
            kwargs=json.loads(entry.kwargs_json),
            queue=entry.original_queue,
            priority=1,
            retry_count=0,
            metadata=json.loads(entry.metadata_json) if entry.metadata_json else {},
        )
        raw = Serializer.serialize(message)
        await broker.enqueue(entry.original_queue, raw)

        task_repo = TaskRepository(session)
        await task_repo.create_task(message)
        await dlq_repo.mark_replayed(entry_id)

    return {
        "task_id": message.task_id,
        "status": "PENDING",
        "original_entry_id": entry_id,
        "queue": message.queue,
    }


@router.post("/replay-all")
async def replay_all(broker: RedisBroker = Depends(get_broker)):
    """Re-submit all non-replayed DLQ entries."""
    replayed_count = 0
    async with get_session() as session:
        dlq_repo = DLQRepository(session)
        entries = await dlq_repo.get_entries(replayed=False, limit=500)
        task_repo = TaskRepository(session)

        for entry in entries:
            message = TaskMessage(
                task_id=str(uuid.uuid4()),
                task_name=entry.task_name,
                args=json.loads(entry.args_json),
                kwargs=json.loads(entry.kwargs_json),
                queue=entry.original_queue,
                priority=1,
                retry_count=0,
            )
            raw = Serializer.serialize(message)
            await broker.enqueue(entry.original_queue, raw)
            await task_repo.create_task(message)
            await dlq_repo.mark_replayed(entry.id)
            replayed_count += 1

    return {"replayed_count": replayed_count}


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str):
    async with get_session() as session:
        repo = DLQRepository(session)
        deleted = await repo.delete_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return {"deleted": True, "entry_id": entry_id}
