"""Single worker process — pulls tasks, executes them, handles retries."""

import asyncio
import json
import os
import signal
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as aioredis

from celerlite.broker.redis_broker import RedisBroker
from celerlite.broker.serializer import Serializer, TaskMessage, TaskResult
from celerlite.config import CelerLiteConfig, config
from celerlite.observability.logger import get_logger
from celerlite.observability.metrics import metrics
from celerlite.persistence.database import AsyncSessionLocal
from celerlite.persistence.repository import DLQRepository, TaskRepository, WorkerRepository
from celerlite.scheduler.retry_policy import RetryPolicy
from celerlite.worker.heartbeat import HeartbeatPublisher

logger = get_logger(__name__)

# Global task registry: task_name → callable
_task_registry: dict[str, Any] = {}


def register_task(name: str, func: Any) -> None:
    _task_registry[name] = func


def get_task(name: str) -> Optional[Any]:
    return _task_registry.get(name)


class TaskTimeoutError(Exception):
    pass


class Worker:
    """
    Single worker — runs in a separate OS process (spawned by WorkerPool).
    Pulls tasks from Redis, executes them, handles retries and DLQ routing.
    """

    def __init__(self, worker_id: str, cfg: CelerLiteConfig = config):
        self.worker_id = worker_id
        self.cfg = cfg
        self._shutdown = threading.Event()
        self._tasks_processed = 0
        self._tasks_failed = 0
        self._current_task_id: Optional[str] = None
        self._broker: Optional[RedisBroker] = None
        self._heartbeat: Optional[HeartbeatPublisher] = None
        self._retry_policy = RetryPolicy(cfg)

    def run(self) -> None:
        """Entry point — called in the child process."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        asyncio.run(self._async_run())

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info("worker_shutdown_signal", worker_id=self.worker_id, signal=signum)
        self._shutdown.set()

    async def _async_run(self) -> None:
        self._broker = RedisBroker(self.cfg)
        await self._broker.connect()
        redis_client = self._broker.client
        self._heartbeat = HeartbeatPublisher(
            self.worker_id, redis_client, ttl=self.cfg.HEARTBEAT_TIMEOUT + 5
        )

        logger.info("worker_started", worker_id=self.worker_id, pid=os.getpid())

        # Heartbeat loop in background
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            while not self._shutdown.is_set():
                await self._process_one()
        finally:
            heartbeat_task.cancel()
            await self._heartbeat.clear()
            await self._broker.disconnect()
            logger.info(
                "worker_stopped",
                worker_id=self.worker_id,
                tasks_processed=self._tasks_processed,
                tasks_failed=self._tasks_failed,
            )

    async def _heartbeat_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self._heartbeat.beat(
                    status="BUSY" if self._current_task_id else "IDLE",
                    current_task_id=self._current_task_id,
                    tasks_processed=self._tasks_processed,
                    tasks_failed=self._tasks_failed,
                    pid=os.getpid(),
                )
            except Exception as e:
                logger.error("heartbeat_error", worker_id=self.worker_id, error=str(e))
            await asyncio.sleep(self.cfg.HEARTBEAT_INTERVAL)

    async def _process_one(self) -> None:
        """Pull one task from the broker and process it."""
        raw = await self._broker.dequeue("default", timeout=5)
        if raw is None:
            return

        try:
            message = Serializer.deserialize(raw)
        except Exception as e:
            logger.error("deserialization_error", error=str(e))
            await self._broker.acknowledge("default", raw)
            return

        # Check if revoked
        if message.revoked or await self._broker.is_revoked(message.task_id):
            logger.info("task_revoked_skip", task_id=message.task_id)
            await self._broker.acknowledge("default", raw)
            await self._update_task_status(message.task_id, "REVOKED")
            return

        # Check ETA — if not ready yet, re-enqueue and skip
        if message.eta:
            eta_ts = datetime.fromisoformat(message.eta).timestamp()
            if time.time() < eta_ts:
                await self._broker.acknowledge("default", raw)
                await self._broker.enqueue("default", raw, priority=message.priority)
                await asyncio.sleep(0.5)
                return

        self._current_task_id = message.task_id
        start_time = time.time()

        await self._broker.publish_event({
            "event": "task_started",
            "task_id": message.task_id,
            "task_name": message.task_name,
            "worker_id": self.worker_id,
            "queue": message.queue,
        })
        await self._update_task_status(message.task_id, "RUNNING", worker_id=self.worker_id)

        try:
            result = await self._execute_with_timeout(message)
            duration_ms = (time.time() - start_time) * 1000

            result_obj = TaskResult(
                task_id=message.task_id,
                status="SUCCESS",
                result=result,
                duration_ms=round(duration_ms, 2),
            )
            result_bytes = Serializer.serialize_result(result_obj)
            await self._broker.store_result(
                message.task_id, result_bytes, ttl=self.cfg.RESULT_TTL
            )
            await self._broker.acknowledge("default", raw)

            self._tasks_processed += 1
            metrics.record_completed(duration_ms)

            await self._update_task_status(
                message.task_id,
                "SUCCESS",
                result_json=json.dumps(result, default=str),
            )
            await self._broker.publish_event({
                "event": "task_completed",
                "task_id": message.task_id,
                "task_name": message.task_name,
                "worker_id": self.worker_id,
                "duration_ms": round(duration_ms, 2),
                "queue": message.queue,
            })
            logger.info(
                "task_success",
                task_id=message.task_id,
                task_name=message.task_name,
                duration_ms=round(duration_ms, 2),
            )

        except Exception as exc:
            await self._handle_failure(message, raw, exc)
        finally:
            self._current_task_id = None

    async def _execute_with_timeout(self, message: TaskMessage) -> Any:
        """Execute task function with timeout enforcement."""
        func = get_task(message.task_name)
        if func is None:
            raise RuntimeError(
                f"Unknown task: '{message.task_name}'. "
                "Ensure the task module is imported before starting workers."
            )

        timeout = message.timeout or self.cfg.TASK_DEFAULT_TIMEOUT

        try:
            if asyncio.iscoroutinefunction(func):
                return await asyncio.wait_for(
                    func(*message.args, **message.kwargs), timeout=timeout
                )
            else:
                # Run sync functions in thread pool to not block the event loop
                loop = asyncio.get_running_loop()
                return await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(*message.args, **message.kwargs)),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            raise TaskTimeoutError(
                f"Task '{message.task_name}' exceeded timeout of {timeout}s"
            )

    async def _handle_failure(self, message: TaskMessage, raw: bytes, error: Exception) -> None:
        """Apply retry policy or route to DLQ."""
        self._tasks_failed += 1
        metrics.record_failed()
        tb = traceback.format_exc()
        logger.error(
            "task_failed",
            task_id=message.task_id,
            task_name=message.task_name,
            error=str(error),
            retry_count=message.retry_count,
        )

        await self._broker.acknowledge("default", raw)

        if self._retry_policy.should_retry(message, error):
            retry_message = self._retry_policy.prepare_retry(message)
            retry_raw = Serializer.serialize(retry_message)
            await self._broker.enqueue("default", retry_raw, priority=message.priority)
            await self._update_task_status(
                message.task_id,
                "RETRYING",
                retry_count=retry_message.retry_count,
                error_message=str(error),
                error_traceback=tb,
            )
            await self._broker.publish_event({
                "event": "task_retried",
                "task_id": message.task_id,
                "task_name": message.task_name,
                "retry_count": retry_message.retry_count,
                "worker_id": self.worker_id,
            })
        else:
            # Send to DLQ
            dlq_data = self._retry_policy.build_dlq_entry(message, error)
            await self._update_task_status(
                message.task_id,
                "DEAD_LETTERED",
                error_message=str(error),
                error_traceback=tb,
            )
            await self._save_to_dlq(dlq_data)
            metrics.record_dead_lettered()
            await self._broker.publish_event({
                "event": "task_dead_lettered",
                "task_id": message.task_id,
                "task_name": message.task_name,
                "worker_id": self.worker_id,
                "error": str(error),
            })
            logger.warning(
                "task_dead_lettered",
                task_id=message.task_id,
                task_name=message.task_name,
                retry_count=message.retry_count,
            )

    async def _update_task_status(self, task_id: str, status: str, **kwargs) -> None:
        try:
            async with AsyncSessionLocal() as session:
                repo = TaskRepository(session)
                await repo.update_status(task_id, status, **kwargs)
                await session.commit()
        except Exception as e:
            logger.error("db_update_failed", task_id=task_id, error=str(e))

    async def _save_to_dlq(self, dlq_data) -> None:
        try:
            async with AsyncSessionLocal() as session:
                repo = DLQRepository(session)
                await repo.add_entry(dlq_data)
                await session.commit()
        except Exception as e:
            logger.error("dlq_save_failed", error=str(e))
