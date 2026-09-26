"""CRUD repository operations for Tasks, Workers, and DLQ."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from celerlite.broker.serializer import TaskMessage
from celerlite.persistence.models import DLQEntry, TaskModel, WorkerModel
from celerlite.scheduler.retry_policy import DLQEntry as DLQData


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_task(self, message: TaskMessage) -> TaskModel:
        task = TaskModel(
            id=message.task_id,
            task_name=message.task_name,
            status="PENDING",
            args_json=json.dumps(message.args),
            kwargs_json=json.dumps(message.kwargs),
            queue=message.queue,
            priority=message.priority,
            retry_count=message.retry_count,
            max_retries=message.max_retries,
            timeout=message.timeout,
            metadata_json=json.dumps(message.metadata) if message.metadata else None,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def update_status(
        self,
        task_id: str,
        status: str,
        worker_id: Optional[str] = None,
        result_json: Optional[str] = None,
        error_message: Optional[str] = None,
        error_traceback: Optional[str] = None,
        retry_count: Optional[int] = None,
    ) -> None:
        values: dict = {"status": status}
        if status == "RUNNING":
            values["started_at"] = utcnow()
            if worker_id:
                values["worker_id"] = worker_id
        if status in ("SUCCESS", "FAILED", "DEAD_LETTERED", "REVOKED"):
            values["completed_at"] = utcnow()
        if result_json is not None:
            values["result_json"] = result_json
        if error_message is not None:
            values["error_message"] = error_message
        if error_traceback is not None:
            values["error_traceback"] = error_traceback
        if retry_count is not None:
            values["retry_count"] = retry_count
            values["status"] = "RETRYING"

        await self.session.execute(
            update(TaskModel).where(TaskModel.id == task_id).values(**values)
        )

    async def get_task(self, task_id: str) -> Optional[TaskModel]:
        result = await self.session.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_tasks(
        self,
        status: Optional[str] = None,
        queue: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskModel]:
        stmt = select(TaskModel).order_by(TaskModel.created_at.desc())
        if status:
            stmt = stmt.where(TaskModel.status == status)
        if queue:
            stmt = stmt.where(TaskModel.queue == queue)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_counts_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(TaskModel.status, func.count(TaskModel.id)).group_by(TaskModel.status)
        )
        return {row[0]: row[1] for row in result.all()}

    async def get_throughput(self, window_minutes: int = 5) -> float:
        """Tasks completed per second in the last N minutes."""
        from datetime import timedelta
        cutoff = utcnow() - timedelta(minutes=window_minutes)
        result = await self.session.execute(
            select(func.count(TaskModel.id)).where(
                TaskModel.status == "SUCCESS",
                TaskModel.completed_at >= cutoff,
            )
        )
        count = result.scalar_one_or_none() or 0
        return round(count / (window_minutes * 60), 2)


class WorkerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_worker(self, worker_id: str, **fields) -> None:
        existing = await self.session.get(WorkerModel, worker_id)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            worker = WorkerModel(id=worker_id, **fields)
            self.session.add(worker)
        await self.session.flush()

    async def get_all_workers(self) -> list[WorkerModel]:
        result = await self.session.execute(select(WorkerModel))
        return list(result.scalars().all())

    async def mark_worker_dead(self, worker_id: str) -> None:
        await self.session.execute(
            update(WorkerModel)
            .where(WorkerModel.id == worker_id)
            .values(status="DEAD")
        )


class DLQRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_entry(self, data: DLQData) -> DLQEntry:
        entry = DLQEntry(
            task_id=data.task_id,
            task_name=data.task_name,
            args_json=data.args_json,
            kwargs_json=data.kwargs_json,
            error_message=data.error_message,
            error_traceback=data.error_traceback,
            retry_count=data.retry_count,
            original_queue=data.original_queue,
            metadata_json=data.metadata_json,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_entries(
        self, replayed: bool = False, limit: int = 50, offset: int = 0
    ) -> list[DLQEntry]:
        stmt = (
            select(DLQEntry)
            .where(DLQEntry.replayed == replayed)
            .order_by(DLQEntry.dead_lettered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_replayed(self, entry_id: str) -> None:
        await self.session.execute(
            update(DLQEntry)
            .where(DLQEntry.id == entry_id)
            .values(replayed=True, replayed_at=utcnow())
        )

    async def get_dlq_count(self, replayed: bool = False) -> int:
        result = await self.session.execute(
            select(func.count(DLQEntry.id)).where(DLQEntry.replayed == replayed)
        )
        return result.scalar_one_or_none() or 0

    async def get_entry(self, entry_id: str) -> Optional[DLQEntry]:
        return await self.session.get(DLQEntry, entry_id)

    async def delete_entry(self, entry_id: str) -> bool:
        entry = await self.get_entry(entry_id)
        if entry:
            await self.session.delete(entry)
            return True
        return False
