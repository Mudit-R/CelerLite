"""Redis-backed reliable queue using the BRPOPLPUSH pattern.

Architecture:
  Each logical queue has FOUR priority sub-queues (Redis lists):
    celerlite:queue:{name}:critical
    celerlite:queue:{name}:high
    celerlite:queue:{name}:normal
    celerlite:queue:{name}:low

  Each priority sub-queue has a corresponding processing queue:
    celerlite:processing:{name}:{priority}

  Dequeue: BRPOPLPUSH atomically pops from the priority queue and pushes to
  the processing queue. This means if a worker crashes, the task is still in
  the processing queue and can be recovered.

  Acknowledge: LREM the message from the processing queue after success.
  Recover: Scan processing queues for tasks older than timeout, move back to pending.

  Results: stored in Redis string keys with TTL:
    celerlite:result:{task_id}

  Events: published to Redis Pub/Sub channel:
    celerlite:events
"""

import json
import time
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from celerlite.broker.base import BaseBroker
from celerlite.broker.serializer import TaskMessage
from celerlite.config import CelerLiteConfig
from celerlite.observability.logger import get_logger
from celerlite.scheduler.priority import (
    Priority,
    get_priority_dequeue_order,
    get_priority_queue_name,
)

logger = get_logger(__name__)

PROCESSING_KEY = "celerlite:processing:{queue}:{priority}"
EVENTS_CHANNEL = "celerlite:events"
RESULT_KEY = "celerlite:result:{task_id}"
TASK_TIMESTAMP_KEY = "celerlite:proc_ts:{queue}:{priority}"


class RedisBroker(BaseBroker):
    """Redis-backed reliable message broker."""

    def __init__(self, config: CelerLiteConfig):
        self.config = config
        self._pool: Optional[aioredis.ConnectionPool] = None
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        self._pool = aioredis.ConnectionPool.from_url(
            self.config.REDIS_URL,
            max_connections=self.config.REDIS_MAX_CONNECTIONS,
            decode_responses=False,
        )
        self._client = aioredis.Redis(connection_pool=self._pool)
        await self._client.ping()
        logger.info("redis_connected", url=self.config.REDIS_URL)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
        if self._pool:
            await self._pool.aclose()
        logger.info("redis_disconnected")

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("RedisBroker not connected. Call connect() first.")
        return self._client

    async def enqueue(self, queue_name: str, message: bytes, priority: int = 1) -> str:
        """Push message to the correct priority sub-queue. Returns the queue key."""
        prio = Priority(priority)
        queue_key = get_priority_queue_name(queue_name, prio)
        await self.client.lpush(queue_key, message)
        logger.debug("task_enqueued", queue=queue_key)
        return queue_key

    async def dequeue(self, queue_name: str, timeout: int = 5) -> Optional[bytes]:
        """
        Try each priority sub-queue in order (critical → low).
        Uses BRPOPLPUSH to atomically move the message to the processing queue.
        Returns the raw message bytes, or None on timeout.
        """
        priority_queues = get_priority_dequeue_order(queue_name)

        # Try non-blocking pop from each priority queue first
        for queue_key in priority_queues:
            priority_suffix = queue_key.split(":")[-1]
            proc_key = PROCESSING_KEY.format(queue=queue_name, priority=priority_suffix)
            ts_key = TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=priority_suffix)

            message = await self.client.rpoplpush(queue_key, proc_key)
            if message is not None:
                # Record timestamp of when this task entered processing
                await self.client.hset(ts_key, message, time.time())
                return message

        # All queues empty — do a blocking wait on the highest-priority queue
        queue_key = priority_queues[0]  # critical queue for blocking
        priority_suffix = queue_key.split(":")[-1]
        proc_key = PROCESSING_KEY.format(queue=queue_name, priority=priority_suffix)
        ts_key = TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=priority_suffix)

        result = await self.client.brpoplpush(queue_key, proc_key, timeout=timeout)
        if result is not None:
            await self.client.hset(ts_key, result, time.time())
        return result

    async def acknowledge(self, queue_name: str, raw_message: bytes) -> None:
        """Remove processed message from ALL processing queues (priority-agnostic cleanup)."""
        for priority in Priority:
            priority_suffix = priority.name.lower()
            proc_key = PROCESSING_KEY.format(queue=queue_name, priority=priority_suffix)
            ts_key = TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=priority_suffix)
            removed = await self.client.lrem(proc_key, 1, raw_message)
            if removed:
                await self.client.hdel(ts_key, raw_message)
                return

    async def reject(self, queue_name: str, raw_message: bytes, requeue: bool = True) -> None:
        """Reject a message — remove from processing. If requeue, push back to queue."""
        await self.acknowledge(queue_name, raw_message)
        if requeue:
            # Re-enqueue at NORMAL priority by default (retry logic sets actual priority)
            await self.enqueue(queue_name, raw_message, priority=Priority.NORMAL)

    async def store_result(self, task_id: str, result: bytes, ttl: int = 86400) -> None:
        key = RESULT_KEY.format(task_id=task_id)
        await self.client.set(key, result, ex=ttl)

    async def get_result(self, task_id: str) -> Optional[bytes]:
        key = RESULT_KEY.format(task_id=task_id)
        return await self.client.get(key)

    async def get_queue_length(self, queue_name: str) -> dict[str, int]:
        """Return pending message counts per priority."""
        lengths = {}
        for priority in Priority:
            queue_key = get_priority_queue_name(queue_name, priority)
            lengths[priority.name.lower()] = await self.client.llen(queue_key)
        return lengths

    async def get_all_queue_lengths(self, queue_names: list[str]) -> dict[str, dict]:
        result = {}
        for name in queue_names:
            result[name] = await self.get_queue_length(name)
        return result

    async def publish_event(self, event: dict) -> None:
        """Publish a real-time lifecycle event."""
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(event)
        await self.client.publish(EVENTS_CHANNEL, payload)

    async def subscribe_events(self):
        """Async generator streaming events from Redis Pub/Sub."""
        import asyncio
        pubsub = self.client.pubsub()
        await pubsub.subscribe(EVENTS_CHANNEL)
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1),
                        timeout=1.0,
                    )
                    if message and message.get("data"):
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        try:
                            yield json.loads(data)
                        except json.JSONDecodeError:
                            pass
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.aclose()


    async def recover_stale_tasks(self, queue_name: str, timeout_seconds: int = 30) -> int:
        """
        Scan all processing queues for tasks that have been there longer than
        timeout_seconds. Move them back to the pending queue.
        Returns the number of tasks recovered.
        """
        recovered = 0
        now = time.time()

        for priority in Priority:
            priority_suffix = priority.name.lower()
            proc_key = PROCESSING_KEY.format(queue=queue_name, priority=priority_suffix)
            ts_key = TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=priority_suffix)

            # Get all messages in the processing queue
            messages = await self.client.lrange(proc_key, 0, -1)
            for msg in messages:
                # Check when it entered processing
                ts_bytes = await self.client.hget(ts_key, msg)
                if ts_bytes is None:
                    # No timestamp = definitely stale, recover it
                    stale = True
                else:
                    enqueued_at = float(ts_bytes)
                    stale = (now - enqueued_at) > timeout_seconds

                if stale:
                    # Remove from processing and put back in pending
                    removed = await self.client.lrem(proc_key, 1, msg)
                    if removed:
                        queue_key = get_priority_queue_name(queue_name, priority)
                        await self.client.lpush(queue_key, msg)
                        await self.client.hdel(ts_key, msg)
                        recovered += 1
                        logger.warning(
                            "stale_task_recovered",
                            queue=queue_name,
                            priority=priority_suffix,
                        )

        return recovered

    async def mark_task_revoked(self, task_id: str) -> None:
        """Store a revocation marker in Redis."""
        key = f"celerlite:revoked:{task_id}"
        await self.client.set(key, "1", ex=86400)

    async def is_revoked(self, task_id: str) -> bool:
        key = f"celerlite:revoked:{task_id}"
        return bool(await self.client.exists(key))

    async def get_redis_info(self) -> dict:
        """Return Redis server info for monitoring."""
        info = await self.client.info("memory")
        return {
            "connected": True,
            "memory_used_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
        }
