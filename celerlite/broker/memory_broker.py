"""In-memory broker for standalone development and zero-dependency execution."""

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from celerlite.broker.base import BaseBroker
from celerlite.config import CelerLiteConfig
from celerlite.observability.logger import get_logger
from celerlite.scheduler.priority import (
    Priority,
    get_priority_dequeue_order,
    get_priority_queue_name,
)

logger = get_logger(__name__)


class MockRedisClient:
    """Mock Redis client so HeartbeatMonitor and RateLimiter can function in standalone mode."""

    def __init__(self, broker: "InMemoryBroker"):
        self._broker = broker

    async def scan_iter(self, match: str = "*", count: int = 100):
        # Return heartbeat keys
        for key in list(self._broker._heartbeats.keys()):
            yield key

    async def hgetall(self, key: str) -> dict:
        return self._broker._heartbeats.get(key, {})

    async def hset(self, key: str, field: str, value: str):
        if key not in self._broker._heartbeats:
            self._broker._heartbeats[key] = {}
        self._broker._heartbeats[key][field] = value

    async def expire(self, key: str, ttl: int):
        pass

    async def delete(self, key: str):
        self._broker._heartbeats.pop(key, None)

    async def zrem(self, key: str, member: str):
        pass

    async def zcount(self, key: str, min_val, max_val) -> int:
        return 0

    def pipeline(self):
        class Pipeline:
            async def execute(self):
                return [0, 0, 1, True]

            def zremrangebyscore(self, *args, **kwargs):
                pass

            def zcard(self, *args, **kwargs):
                pass

            def zadd(self, *args, **kwargs):
                pass

            def expire(self, *args, **kwargs):
                pass

            def hset(self, *args, **kwargs):
                pass

        return Pipeline()


class InMemoryBroker(BaseBroker):
    """
    High-performance in-memory broker.
    Provides strict priority queuing, late ACK, event pub/sub,
    and result caching without needing external Redis.
    """

    def __init__(self, config: CelerLiteConfig):
        self.config = config
        # queue_name -> priority_int -> deque of bytes
        self._queues: dict[str, dict[int, deque]] = defaultdict(
            lambda: {
                Priority.CRITICAL: deque(),
                Priority.HIGH: deque(),
                Priority.NORMAL: deque(),
                Priority.LOW: deque(),
            }
        )
        # queue_name -> dict of raw_message -> entry_time
        self._processing: dict[str, dict[bytes, float]] = defaultdict(dict)
        # task_id -> (result_bytes, expiry_time)
        self._results: dict[str, tuple[bytes, float]] = {}
        # task_id -> expiry_time
        self._revoked: dict[str, float] = {}
        # worker_id -> dict of heartbeat fields
        self._heartbeats: dict[str, dict] = {}
        # Broadcast subscriber queues
        self._subscribers: set[asyncio.Queue] = set()
        self._new_item_event = asyncio.Event()
        self._client = MockRedisClient(self)
        self._connected = True

    async def connect(self) -> None:
        self._connected = True
        logger.info("memory_broker_connected", mode="in-memory-standalone")

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("memory_broker_disconnected")

    @property
    def client(self) -> MockRedisClient:
        return self._client

    async def enqueue(self, queue_name: str, message: bytes, priority: int = 1) -> str:
        prio = Priority(priority)
        self._queues[queue_name][prio].append(message)
        self._new_item_event.set()
        queue_key = get_priority_queue_name(queue_name, prio)
        logger.debug("task_enqueued_memory", queue=queue_key, priority=prio.name)
        return queue_key

    async def dequeue(self, queue_name: str, timeout: int = 5) -> Optional[bytes]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            # Drain in strict priority order: CRITICAL -> HIGH -> NORMAL -> LOW
            for prio in [Priority.CRITICAL, Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                q = self._queues[queue_name][prio]
                if q:
                    msg = q.popleft()
                    self._processing[queue_name][msg] = time.time()
                    return msg

            # Wait for new items or timeout
            remaining = max(0.01, deadline - time.time())
            try:
                await asyncio.wait_for(self._new_item_event.wait(), timeout=min(0.2, remaining))
                self._new_item_event.clear()
            except asyncio.TimeoutError:
                pass

        return None

    async def acknowledge(self, queue_name: str, raw_message: bytes) -> None:
        self._processing[queue_name].pop(raw_message, None)

    async def reject(self, queue_name: str, raw_message: bytes, requeue: bool = True) -> None:
        await self.acknowledge(queue_name, raw_message)
        if requeue:
            await self.enqueue(queue_name, raw_message, priority=Priority.NORMAL)

    async def store_result(self, task_id: str, result: bytes, ttl: int = 86400) -> None:
        self._results[task_id] = (result, time.time() + ttl)

    async def get_result(self, task_id: str) -> Optional[bytes]:
        if task_id in self._results:
            result, expiry = self._results[task_id]
            if time.time() < expiry:
                return result
            del self._results[task_id]
        return None

    async def get_queue_length(self, queue_name: str) -> dict[str, int]:
        lengths = {}
        for priority in Priority:
            lengths[priority.name.lower()] = len(self._queues[queue_name][priority])
        return lengths

    async def get_all_queue_lengths(self, queue_names: list[str]) -> dict[str, dict]:
        return {name: await self.get_queue_length(name) for name in queue_names}

    async def publish_event(self, event: dict) -> None:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        # Broadcast to all live WebSocket subscribers
        dead_subs = set()
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                dead_subs.add(q)
        self._subscribers -= dead_subs

    async def subscribe_events(self) -> AsyncIterator[dict]:
        """Async generator yielding real-time events as they occur."""
        q = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        try:
            while self._connected:
                event = await q.get()
                yield event
        finally:
            self._subscribers.discard(q)

    async def recover_stale_tasks(self, queue_name: str, timeout_seconds: int = 30) -> int:
        now = time.time()
        recovered = 0
        stale_messages = []
        for msg, entry_time in self._processing[queue_name].items():
            if (now - entry_time) > timeout_seconds:
                stale_messages.append(msg)

        for msg in stale_messages:
            self._processing[queue_name].pop(msg, None)
            # Requeue at normal priority
            self._queues[queue_name][Priority.NORMAL].append(msg)
            recovered += 1

        if recovered > 0:
            self._new_item_event.set()
        return recovered

    async def mark_task_revoked(self, task_id: str) -> None:
        self._revoked[task_id] = time.time() + 86400

    async def is_revoked(self, task_id: str) -> bool:
        if task_id in self._revoked:
            if time.time() < self._revoked[task_id]:
                return True
            del self._revoked[task_id]
        return False

    async def get_redis_info(self) -> dict:
        total_items = sum(
            len(q[p]) for q in self._queues.values() for p in Priority
        )
        return {
            "connected": True,
            "mode": "in-memory (standalone)",
            "memory_used_mb": round(total_items * 0.001 + 0.5, 2),
        }
