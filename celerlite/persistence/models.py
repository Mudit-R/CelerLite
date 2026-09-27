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


class LeadModel(Base):
    __tablename__ = "crm_leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="New")
    lead_source: Mapped[str] = mapped_column(String(100), nullable=False, default="Web")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    annual_revenue: Mapped[float | None] = mapped_column(BigInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str] = mapped_column(String(100), nullable=False, default="Alex Chen")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "name": f"{self.first_name} {self.last_name}",
            "company": self.company,
            "title": self.title or "",
            "email": self.email,
            "phone": self.phone or "",
            "status": self.status,
            "lead_source": self.lead_source,
            "score": self.score,
            "annual_revenue": self.annual_revenue,
            "notes": self.notes or "",
            "owner": self.owner,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AccountModel(Base):
    __tablename__ = "crm_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=False, default="Technology")
    annual_revenue: Mapped[float] = mapped_column(BigInteger, nullable=False, default=1000000)
    employees: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tier: Mapped[str] = mapped_column(String(50), nullable=False, default="Enterprise")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "industry": self.industry,
            "annual_revenue": self.annual_revenue,
            "employees": self.employees,
            "website": self.website or "",
            "phone": self.phone or "",
            "billing_city": self.billing_city or "",
            "billing_country": self.billing_country or "",
            "tier": self.tier,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ContactModel(Base):
    __tablename__ = "crm_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "account_name": self.account_name or "",
            "first_name": self.first_name,
            "last_name": self.last_name,
            "name": f"{self.first_name} {self.last_name}",
            "email": self.email,
            "phone": self.phone or "",
            "title": self.title or "",
            "department": self.department or "",
            "is_primary": self.is_primary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DealModel(Base):
    __tablename__ = "crm_deals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), nullable=False, default="Prospecting")
    amount: Mapped[float] = mapped_column(BigInteger, nullable=False, default=50000)
    probability: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    close_date: Mapped[str] = mapped_column(String(20), nullable=False)
    deal_type: Mapped[str] = mapped_column(String(50), nullable=False, default="New Business")
    owner: Mapped[str] = mapped_column(String(100), nullable=False, default="Alex Chen")
    next_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "name": self.name,
            "stage": self.stage,
            "amount": self.amount,
            "probability": self.probability,
            "close_date": self.close_date,
            "deal_type": self.deal_type,
            "owner": self.owner,
            "next_step": self.next_step or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ActivityModel(Base):
    __tablename__ = "crm_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # lead, deal, account, contact
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    entity_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="Task")  # Call, Email, Meeting, Task, Note
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="Pending")  # Pending, Completed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name or "",
            "type": self.type,
            "subject": self.subject,
            "description": self.description or "",
            "due_date": self.due_date or "",
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


