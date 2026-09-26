"""Unit tests for TaskRepository, WorkerRepository, and DLQRepository using SQLite async."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from celerlite.persistence.models import Base
from celerlite.persistence.repository import TaskRepository, WorkerRepository, DLQRepository
from celerlite.broker.serializer import TaskMessage
from celerlite.scheduler.retry_policy import DLQEntry as DLQData


@pytest_asyncio.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
class TestTaskRepository:
    async def test_create_and_get_task(self, async_session):
        repo = TaskRepository(async_session)
        msg = TaskMessage(
            task_id="t-101",
            task_name="tasks.add",
            args=[10, 20],
            kwargs={"precision": 2},
            queue="math",
            priority=2,
        )
        task = await repo.create_task(msg)
        await async_session.commit()

        assert task.id == "t-101"
        assert task.status == "PENDING"
        assert task.priority == 2

        fetched = await repo.get_task("t-101")
        assert fetched is not None
        assert fetched.task_name == "tasks.add"
        assert fetched.queue == "math"

    async def test_update_status_and_counts(self, async_session):
        repo = TaskRepository(async_session)
        msg = TaskMessage(task_id="t-102", task_name="tasks.sub", args=[5, 3], kwargs={})
        await repo.create_task(msg)
        await async_session.commit()

        await repo.update_status("t-102", "RUNNING", worker_id="worker-node-1")
        await async_session.commit()

        task = await repo.get_task("t-102")
        assert task.status == "RUNNING"
        assert task.worker_id == "worker-node-1"
        assert task.started_at is not None

        await repo.update_status("t-102", "SUCCESS", result_json="2")
        await async_session.commit()

        task = await repo.get_task("t-102")
        assert task.status == "SUCCESS"
        assert task.result_json == "2"
        assert task.completed_at is not None

        counts = await repo.get_counts_by_status()
        assert counts.get("SUCCESS") == 1

    async def test_filter_tasks_by_queue_and_status(self, async_session):
        repo = TaskRepository(async_session)
        msg1 = TaskMessage(task_id="t-q1", task_name="t1", args=[], kwargs={}, queue="batch")
        msg2 = TaskMessage(task_id="t-q2", task_name="t2", args=[], kwargs={}, queue="interactive")
        await repo.create_task(msg1)
        await repo.create_task(msg2)
        await async_session.commit()

        batch_tasks = await repo.get_tasks(queue="batch")
        assert len(batch_tasks) == 1
        assert batch_tasks[0].id == "t-q1"


@pytest.mark.asyncio
class TestWorkerRepository:
    async def test_upsert_and_mark_dead(self, async_session):
        repo = WorkerRepository(async_session)
        await repo.upsert_worker("w-1", pid=5001, hostname="host-a", status="ONLINE")
        await async_session.commit()

        workers = await repo.get_all_workers()
        assert len(workers) == 1
        assert workers[0].id == "w-1"
        assert workers[0].hostname == "host-a"

        # Update tasks_processed
        await repo.upsert_worker("w-1", tasks_processed=15)
        await async_session.commit()
        worker = (await repo.get_all_workers())[0]
        assert worker.tasks_processed == 15

        # Mark dead
        await repo.mark_worker_dead("w-1")
        await async_session.commit()
        worker = (await repo.get_all_workers())[0]
        assert worker.status == "DEAD"


@pytest.mark.asyncio
class TestDLQRepository:
    async def test_dlq_crud(self, async_session):
        repo = DLQRepository(async_session)
        dlq_data = DLQData(
            task_id="dlq-task-1",
            task_name="tasks.flake",
            args_json="[]",
            kwargs_json="{}",
            error_message="Permanent failure",
            error_traceback="Traceback...",
            retry_count=3,
            original_queue="default",
            metadata_json=None,
        )

        entry = await repo.add_entry(dlq_data)
        await async_session.commit()

        assert entry.id is not None
        assert entry.task_id == "dlq-task-1"
        assert entry.replayed is False

        count = await repo.get_dlq_count(replayed=False)
        assert count == 1

        entries = await repo.get_entries(replayed=False)
        assert len(entries) == 1

        # Mark replayed
        await repo.mark_replayed(entry.id)
        await async_session.commit()

        count_after = await repo.get_dlq_count(replayed=False)
        assert count_after == 0

        # Delete entry
        deleted = await repo.delete_entry(entry.id)
        await async_session.commit()
        assert deleted is True
