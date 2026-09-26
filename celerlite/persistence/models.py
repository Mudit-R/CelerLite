"""SQLAlchemy 2.0 ORM models for task persistence."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )  # PENDING|RUNNING|SUCCESS|FAILED|RETRYING|DEAD_LETTERED|REVOKED
    args_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    kwargs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    queue: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_task_name", "task_name"),
        Index("ix_tasks_created_at", "created_at"),
        Index("ix_tasks_queue_status", "queue", "status"),
    )

    def __init__(self, **kwargs):
        if "id" not in kwargs or kwargs["id"] is None:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "PENDING"
        if "args_json" not in kwargs:
            kwargs["args_json"] = "[]"
        if "kwargs_json" not in kwargs:
            kwargs["kwargs_json"] = "{}"
        if "queue" not in kwargs:
            kwargs["queue"] = "default"
        if "priority" not in kwargs:
            kwargs["priority"] = 1
        if "retry_count" not in kwargs:
            kwargs["retry_count"] = 0
        if "max_retries" not in kwargs:
            kwargs["max_retries"] = 3
        if "timeout" not in kwargs:
            kwargs["timeout"] = 300
        if "created_at" not in kwargs:
            kwargs["created_at"] = utcnow()
        super().__init__(**kwargs)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_name": self.task_name,
            "status": self.status,
            "args_json": self.args_json,
            "kwargs_json": self.kwargs_json,
            "result_json": self.result_json,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "queue": self.queue,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "worker_id": self.worker_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "eta": self.eta.isoformat() if self.eta else None,
            "timeout": self.timeout,
            "metadata_json": self.metadata_json,
        }


class WorkerModel(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ONLINE"
    )  # ONLINE|OFFLINE|DEAD
    tasks_processed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tasks_failed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __init__(self, **kwargs):
        if "status" not in kwargs:
            kwargs["status"] = "ONLINE"
        if "tasks_processed" not in kwargs:
            kwargs["tasks_processed"] = 0
        if "tasks_failed" not in kwargs:
            kwargs["tasks_failed"] = 0
        if "started_at" not in kwargs:
            kwargs["started_at"] = utcnow()
        super().__init__(**kwargs)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pid": self.pid,
            "hostname": self.hostname,
            "status": self.status,
            "tasks_processed": self.tasks_processed,
            "tasks_failed": self.tasks_failed,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "current_task_id": self.current_task_id,
        }


class DLQEntry(Base):
    __tablename__ = "dlq_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    args_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    kwargs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_queue: Mapped[str] = mapped_column(String(100), nullable=False)
    dead_lettered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_dlq_replayed", "replayed"),
        Index("ix_dlq_dead_lettered_at", "dead_lettered_at"),
    )

    def __init__(self, **kwargs):
        if "id" not in kwargs or kwargs["id"] is None:
            kwargs["id"] = str(uuid.uuid4())
        if "replayed" not in kwargs:
            kwargs["replayed"] = False
        if "dead_lettered_at" not in kwargs:
            kwargs["dead_lettered_at"] = utcnow()
        super().__init__(**kwargs)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "args_json": self.args_json,
            "kwargs_json": self.kwargs_json,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "retry_count": self.retry_count,
            "original_queue": self.original_queue,
            "dead_lettered_at": self.dead_lettered_at.isoformat() if self.dead_lettered_at else None,
            "replayed": self.replayed,
            "replayed_at": self.replayed_at.isoformat() if self.replayed_at else None,
            "metadata_json": self.metadata_json,
        }

