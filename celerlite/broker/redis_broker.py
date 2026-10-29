"""Redis-backed at-least-once queue using atomic Lua transitions.

Architecture:
  Each logical queue has FOUR priority sub-queues (Redis lists):
    celerlite:queue:{name}:critical
    celerlite:queue:{name}:high
    celerlite:queue:{name}:normal
    celerlite:queue:{name}:low

  Each priority sub-queue has a corresponding processing queue:
    celerlite:processing:{name}:{priority}

  Dequeue: a Lua script moves work to processing and records server time in
  one atomic reservation. Idle consumers check every priority, not just critical.

  Acknowledge/reject/recover: Lua transitions keep processing lists, timestamps
  and requeued work consistent. Business side effects must still be idempotent.

  Results: stored in Redis string keys with TTL:
    celerlite:result:{task_id}

  Events: published to Redis Pub/Sub channel:
    celerlite:events
"""

import asyncio
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

# A reservation and its timestamp must be visible together. All keys belong to
# one logical queue; Redis Cluster is not supported by this list-based broker.
RESERVE_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
for i = 1, #KEYS, 3 do
    local message = redis.call('RPOPLPUSH', KEYS[i], KEYS[i + 1])
    if message then
        redis.call('HSET', KEYS[i + 2], message, now)
        return message
    end
end
return false
"""

FINISH_SCRIPT = """
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
if removed > 0 then
    redis.call('HDEL', KEYS[2], ARGV[1])
    if ARGV[2] == 'requeue' then
        redis.call('LPUSH', KEYS[3], ARGV[1])
    end
end
return removed
"""

REPLACE_SCRIPT = """
if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 0 then return 0 end
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('LPUSH', KEYS[3], ARGV[2])
return 1
"""

RECOVER_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local recovered = 0
for _, message in ipairs(redis.call('LRANGE', KEYS[1], 0, -1)) do
    local reserved = redis.call('HGET', KEYS[2], message)
    if not reserved or now - tonumber(reserved) >= tonumber(ARGV[1]) then
        if redis.call('LREM', KEYS[1], 1, message) > 0 then
            redis.call('LPUSH', KEYS[3], message)
            redis.call('HDEL', KEYS[2], message)
            recovered = recovered + 1
        end
    end
end
return recovered
"""


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
        """Poll all priorities, atomically reserving a message and timestamp.

        Positive timeout bounds the wait; zero waits until work arrives. Short
        cancellable sleeps avoid blocking exclusively on the critical queue.
        """
        if timeout < 0:
            raise ValueError('timeout must be non-negative')
        keys = []
        for pending in get_priority_dequeue_order(queue_name):
            suffix = pending.rsplit(':', 1)[1]
            keys.extend([pending,
                         PROCESSING_KEY.format(queue=queue_name, priority=suffix),
                         TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=suffix)])
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            message = await self.client.eval(RESERVE_SCRIPT, len(keys), *keys)
            if message is not None:
                return message
            remaining = deadline - time.monotonic() if deadline is not None else 0.05
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.05, remaining))

    async def acknowledge(self, queue_name: str, raw_message: bytes) -> None:
        """Remove processed message from ALL processing queues (priority-agnostic cleanup)."""
        for priority in Priority:
            priority_suffix = priority.name.lower()
            proc_key = PROCESSING_KEY.format(queue=queue_name, priority=priority_suffix)
            ts_key = TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=priority_suffix)
            pending = get_priority_queue_name(queue_name, priority)
            removed = await self.client.eval(FINISH_SCRIPT, 3, proc_key, ts_key,
                                             pending, raw_message, 'ack')
            if removed:
                return

    async def reject(self, queue_name: str, raw_message: bytes, requeue: bool = True) -> None:
        """Reject a message — remove from processing. If requeue, push back to queue."""
        for priority in Priority:
            suffix = priority.name.lower()
            removed = await self.client.eval(
                FINISH_SCRIPT, 3,
                PROCESSING_KEY.format(queue=queue_name, priority=suffix),
                TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=suffix),
                get_priority_queue_name(queue_name, priority), raw_message,
                'requeue' if requeue else 'ack')
            if removed:
                return

    async def replace_reserved(self, queue_name: str, raw_message: bytes,
                               replacement: bytes, priority: int) -> bool:
        """Atomically replace a reserved message with a modified retry payload.

        Returns false when recovery or another consumer already removed it.
        """
        pending = get_priority_queue_name(queue_name, Priority(priority))
        for source_priority in Priority:
            suffix = source_priority.name.lower()
            moved = await self.client.eval(
                REPLACE_SCRIPT, 3,
                PROCESSING_KEY.format(queue=queue_name, priority=suffix),
                TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=suffix),
                pending, raw_message, replacement)
            if moved:
                return True
        return False

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
        if timeout_seconds < 0:
            raise ValueError('timeout_seconds must be non-negative')

        for priority in Priority:
            priority_suffix = priority.name.lower()
            proc_key = PROCESSING_KEY.format(queue=queue_name, priority=priority_suffix)
            ts_key = TASK_TIMESTAMP_KEY.format(queue=queue_name, priority=priority_suffix)

            recovered += int(await self.client.eval(
                RECOVER_SCRIPT, 3, proc_key, ts_key,
                get_priority_queue_name(queue_name, priority), timeout_seconds))

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
