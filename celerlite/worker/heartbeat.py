"""Heartbeat publisher and monitor for worker liveness detection."""

import json
import socket
import time
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

HEARTBEAT_KEY = "celerlite:heartbeat:{worker_id}"
HEARTBEAT_PATTERN = "celerlite:heartbeat:*"


class HeartbeatPublisher:
    """Publishes heartbeats from inside a worker process."""

    def __init__(self, worker_id: str, redis_client: aioredis.Redis, ttl: int = 35):
        self.worker_id = worker_id
        self._client = redis_client
        self._ttl = ttl
        self._key = HEARTBEAT_KEY.format(worker_id=worker_id)

    async def beat(
        self,
        status: str = "IDLE",
        current_task_id: Optional[str] = None,
        tasks_processed: int = 0,
        tasks_failed: int = 0,
        pid: Optional[int] = None,
    ) -> None:
        """Write current state to Redis with TTL."""
        import os

        data = {
            "worker_id": self.worker_id,
            "pid": pid or os.getpid(),
            "hostname": socket.gethostname(),
            "status": status,
            "current_task_id": current_task_id or "",
            "tasks_processed": tasks_processed,
            "tasks_failed": tasks_failed,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }
        pipe = self._client.pipeline()
        for field, value in data.items():
            pipe.hset(self._key, field, str(value))
        pipe.expire(self._key, self._ttl)
        await pipe.execute()

    async def clear(self) -> None:
        """Remove heartbeat key on clean shutdown."""
        await self._client.delete(self._key)


class HeartbeatMonitor:
    """Reads heartbeat data to detect dead workers."""

    def __init__(self, redis_client: aioredis.Redis, heartbeat_timeout: int = 30):
        self._client = redis_client
        self._timeout = heartbeat_timeout

    async def get_all_heartbeats(self) -> list[dict]:
        """Scan for all worker heartbeat keys and return their data."""
        keys = []
        async for key in self._client.scan_iter(match=HEARTBEAT_PATTERN, count=100):
            keys.append(key)

        heartbeats = []
        for key in keys:
            data = await self._client.hgetall(key)
            if data:
                decoded = {
                    k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                    for k, v in data.items()
                }
                heartbeats.append(decoded)
        return heartbeats

    async def get_stale_workers(self) -> list[str]:
        """Return worker_ids whose last heartbeat exceeded the timeout."""
        stale = []
        heartbeats = await self.get_all_heartbeats()
        now = time.time()

        for hb in heartbeats:
            last_hb_str = hb.get("last_heartbeat", "")
            if not last_hb_str:
                stale.append(hb["worker_id"])
                continue
            try:
                last_hb_dt = datetime.fromisoformat(last_hb_str)
                last_hb_ts = last_hb_dt.timestamp()
                if (now - last_hb_ts) > self._timeout:
                    stale.append(hb["worker_id"])
            except (ValueError, OSError):
                stale.append(hb["worker_id"])

        return stale
