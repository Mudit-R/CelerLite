"""Embedded background worker for standalone mode (no external worker process needed)."""

import asyncio
import json
import time
from typing import Optional

from celerlite.broker.base import BaseBroker
from celerlite.broker.serializer import Serializer, TaskResult
from celerlite.observability.logger import get_logger
from celerlite.observability.metrics import metrics
from celerlite.persistence.database import get_session
from celerlite.persistence.repository import TaskRepository, WorkerRepository
from celerlite.worker.worker import get_task, register_task

logger = get_logger(__name__)

# Register standard demo tasks
register_task("celerlite.demo.add", lambda a, b: a + b)
register_task("celerlite.demo.multiply", lambda a, b: a * b)
register_task("celerlite.demo.heavy_computation", lambda n=1000: sum(i * i for i in range(n)))
register_task("celerlite.demo.send_email", lambda to, subject: f"Sent to {to}: {subject}")


async def run_embedded_worker(
    broker: BaseBroker,
    worker_id: str = "worker-standalone-1",
    stop_event: Optional[asyncio.Event] = None,
):
    """Continuously poll broker for tasks and execute them in-process."""
    logger.info("embedded_worker_started", worker_id=worker_id)
    queues = ["default", "emails", "payments", "high_priority"]
    processed = 0
    failed = 0

    # Register worker in repository
    try:
        async with get_session() as session:
            w_repo = WorkerRepository(session)
            await w_repo.upsert_worker(
                worker_id, pid=1, hostname="localhost", status="ONLINE"
            )
    except Exception as e:
        logger.debug("worker_upsert_ignored", error=str(e))

    while stop_event is None or not stop_event.is_set():
        # Beat heartbeat
        try:
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await broker.client.hset(
                f"celerlite:heartbeat:{worker_id}", "worker_id", worker_id
            )
            await broker.client.hset(
                f"celerlite:heartbeat:{worker_id}", "status", "IDLE"
            )
            await broker.client.hset(
                f"celerlite:heartbeat:{worker_id}", "tasks_processed", str(processed)
            )
            await broker.client.hset(
                f"celerlite:heartbeat:{worker_id}", "tasks_failed", str(failed)
            )
            await broker.client.hset(
                f"celerlite:heartbeat:{worker_id}", "last_heartbeat", now_iso
            )
            await broker.client.hset(
                f"celerlite:heartbeat:{worker_id}", "hostname", "localhost"
            )
        except Exception:
            pass

        # Dequeue from available queues
        raw_msg = None
        target_queue = "default"
        for q_name in queues:
            try:
                raw_msg = await broker.dequeue(q_name, timeout=0.1)
                if raw_msg:
                    target_queue = q_name
                    break
            except Exception:
                pass

        if not raw_msg:
            await asyncio.sleep(0.1)
            continue

        # Execute task
        try:
            message = Serializer.deserialize(raw_msg)
        except Exception as e:
            logger.error("deserialize_failed", error=str(e))
            continue

        start_time = time.time()
        logger.info(
            "embedded_worker_task_started",
            task_id=message.task_id,
            task_name=message.task_name,
        )

        # Notify start
        await broker.publish_event({
            "event": "task_started",
            "task_id": message.task_id,
            "task_name": message.task_name,
            "worker_id": worker_id,
            "queue": target_queue,
        })

        try:
            async with get_session() as session:
                t_repo = TaskRepository(session)
                await t_repo.update_status(
                    message.task_id, "RUNNING", worker_id=worker_id
                )
        except Exception:
            pass

        # Execute
        func = get_task(message.task_name)
        task_success = True
        error_msg = None
        result_val = None

        try:
            if func is not None:
                if asyncio.iscoroutinefunction(func):
                    result_val = await func(*message.args, **message.kwargs)
                else:
                    result_val = func(*message.args, **message.kwargs)
            else:
                # Default demo behavior for demo tasks
                if "add" in message.task_name:
                    result_val = sum(message.args) if message.args else 42
                elif "fail" in message.task_name or "flake" in message.task_name:
                    raise ValueError("Simulated task failure for testing")
                else:
                    result_val = {
                        "status": "ok",
                        "task": message.task_name,
                        "args": message.args,
                    }
        except Exception as err:
            task_success = False
            error_msg = str(err)

        duration_ms = round((time.time() - start_time) * 1000, 2)
        metrics.record_completed(duration_ms)

        if task_success:
            processed += 1
            res = TaskResult(
                task_id=message.task_id,
                status="SUCCESS",
                result=result_val,
                duration_ms=duration_ms,
            )
            raw_res = Serializer.serialize_result(res)
            await broker.store_result(message.task_id, raw_res)
            await broker.acknowledge(target_queue, raw_msg)

            try:
                async with get_session() as session:
                    t_repo = TaskRepository(session)
                    await t_repo.update_status(
                        message.task_id,
                        "SUCCESS",
                        result_json=json.dumps(result_val),
                    )
            except Exception:
                pass

            await broker.publish_event({
                "event": "task_completed",
                "task_id": message.task_id,
                "task_name": message.task_name,
                "worker_id": worker_id,
                "duration_ms": duration_ms,
                "queue": target_queue,
            })
        else:
            failed += 1
            metrics.record_failed()
            res = TaskResult(
                task_id=message.task_id,
                status="FAILED",
                error=error_msg,
                duration_ms=duration_ms,
            )
            raw_res = Serializer.serialize_result(res)
            await broker.store_result(message.task_id, raw_res)
            await broker.acknowledge(target_queue, raw_msg)

            try:
                async with get_session() as session:
                    t_repo = TaskRepository(session)
                    await t_repo.update_status(
                        message.task_id,
                        "FAILED",
                        error_message=error_msg,
                    )
            except Exception:
                pass

            await broker.publish_event({
                "event": "task_failed",
                "task_id": message.task_id,
                "task_name": message.task_name,
                "worker_id": worker_id,
                "error": error_msg,
                "duration_ms": duration_ms,
                "queue": target_queue,
            })
