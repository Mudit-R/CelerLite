"""The @task decorator and AsyncResult SDK — user-facing API."""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Optional

from celerlite.broker.redis_broker import RedisBroker
from celerlite.broker.serializer import Serializer, TaskMessage, TaskResult
from celerlite.config import config as _config
from celerlite.observability.logger import get_logger
from celerlite.observability.metrics import metrics
from celerlite.persistence.database import AsyncSessionLocal
from celerlite.persistence.repository import TaskRepository
from celerlite.scheduler.priority import Priority
from celerlite.worker.worker import register_task

logger = get_logger(__name__)

# Module-level broker shared across the process
_broker: Optional[RedisBroker] = None


async def _get_broker() -> RedisBroker:
    global _broker
    if _broker is None:
        _broker = RedisBroker(_config)
        await _broker.connect()
    return _broker


class TaskError(Exception):
    """Raised by AsyncResult.get() when the task failed."""

    def __init__(self, message: str, traceback: Optional[str] = None):
        super().__init__(message)
        self.traceback = traceback


class AsyncResult:
    """Handle to a submitted task. Allows polling for status and result."""

    def __init__(self, task_id: str):
        self.task_id = task_id

    @property
    def status(self) -> str:
        """Synchronously check status via database."""
        return asyncio.get_event_loop().run_until_complete(self._async_status())

    async def _async_status(self) -> str:
        async with AsyncSessionLocal() as session:
            repo = TaskRepository(session)
            task = await repo.get_task(self.task_id)
            return task.status if task else "UNKNOWN"

    async def _async_result(self) -> TaskResult:
        broker = await _get_broker()
        raw = await broker.get_result(self.task_id)
        if raw is None:
            return None
        return Serializer.deserialize_result(raw)

    def get(self, timeout: float = 30.0, interval: float = 0.5) -> Any:
        """
        Block until the task completes. Raises TimeoutError or TaskError.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = asyncio.get_event_loop().run_until_complete(self._async_result())
            if result is not None:
                if result.status == "FAILED":
                    raise TaskError(result.error or "Task failed", result.traceback)
                return result.result
            time.sleep(interval)
        raise TimeoutError(f"Task {self.task_id} did not complete within {timeout}s")

    def revoke(self) -> None:
        """Mark the task as revoked so workers skip it."""
        asyncio.get_event_loop().run_until_complete(self._async_revoke())

    async def _async_revoke(self) -> None:
        broker = await _get_broker()
        await broker.mark_task_revoked(self.task_id)
        logger.info("task_revoked", task_id=self.task_id)

    @property
    def is_ready(self) -> bool:
        return asyncio.get_event_loop().run_until_complete(self._async_result()) is not None

    @property
    def is_successful(self) -> bool:
        r = asyncio.get_event_loop().run_until_complete(self._async_result())
        return r is not None and r.status == "SUCCESS"

    @property
    def is_failed(self) -> bool:
        r = asyncio.get_event_loop().run_until_complete(self._async_result())
        return r is not None and r.status == "FAILED"

    def __repr__(self) -> str:
        return f"AsyncResult(task_id={self.task_id!r})"


class TaskDecorator:
    """Wraps a function to add .delay() and .apply_async() methods."""

    def __init__(
        self,
        func: Callable,
        queue: str = "default",
        max_retries: int = 3,
        timeout: int = 300,
        rate_limit: Optional[str] = None,
        name: Optional[str] = None,
    ):
        self._func = func
        self.queue = queue
        self.max_retries = max_retries
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.name = name or f"{func.__module__}.{func.__qualname__}"

        # Register in the global task registry (inherited by workers via fork)
        register_task(self.name, func)

        # Preserve function metadata
        wraps(func)(self)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Direct call — executes immediately in the current process."""
        return self._func(*args, **kwargs)

    def delay(self, *args: Any, **kwargs: Any) -> AsyncResult:
        """Shortcut for apply_async with positional + keyword args."""
        return self.apply_async(args=list(args), kwargs=kwargs)

    def apply_async(
        self,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        queue: Optional[str] = None,
        priority: Priority = Priority.NORMAL,
        eta: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> AsyncResult:
        """Submit the task to the broker. Returns AsyncResult immediately."""
        message = TaskMessage(
            task_id=str(uuid.uuid4()),
            task_name=self.name,
            args=args or [],
            kwargs=kwargs or {},
            queue=queue or self.queue,
            priority=int(priority),
            max_retries=self.max_retries,
            timeout=self.timeout,
            eta=eta.isoformat() if eta else None,
            metadata=metadata or {},
        )

        # Submit to broker (run in event loop)
        asyncio.get_event_loop().run_until_complete(self._submit(message))
        metrics.record_submitted()
        return AsyncResult(message.task_id)

    async def _submit(self, message: TaskMessage) -> None:
        broker = await _get_broker()
        raw = Serializer.serialize(message)
        await broker.enqueue(message.queue, raw, priority=message.priority)

        # Persist to PostgreSQL
        try:
            async with AsyncSessionLocal() as session:
                repo = TaskRepository(session)
                await repo.create_task(message)
                await session.commit()
        except Exception as e:
            logger.error("task_persist_failed", task_id=message.task_id, error=str(e))

        # Publish event
        await broker.publish_event({
            "event": "task_submitted",
            "task_id": message.task_id,
            "task_name": message.task_name,
            "queue": message.queue,
            "priority": message.priority,
        })
        logger.info(
            "task_submitted",
            task_id=message.task_id,
            task_name=message.task_name,
            queue=message.queue,
        )


def task(
    func: Optional[Callable] = None,
    *,
    queue: str = "default",
    max_retries: int = _config.MAX_RETRIES,
    timeout: int = _config.TASK_DEFAULT_TIMEOUT,
    rate_limit: Optional[str] = None,
    name: Optional[str] = None,
) -> Any:
    """
    Decorator that turns a function into a CelerLite task.

    Usage:
        @task
        def my_task(x, y): return x + y

        @task(queue="emails", max_retries=5)
        def send_email(to, subject): ...

        result = my_task.delay(1, 2)
        result.get(timeout=10)  # returns 3
    """
    if func is not None:
        # Called without arguments: @task
        return TaskDecorator(func, queue=queue, max_retries=max_retries, timeout=timeout)

    # Called with arguments: @task(queue="x")
    def decorator(f: Callable) -> TaskDecorator:
        return TaskDecorator(
            f,
            queue=queue,
            max_retries=max_retries,
            timeout=timeout,
            rate_limit=rate_limit,
            name=name,
        )

    return decorator
