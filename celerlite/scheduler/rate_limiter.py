"""Distributed token bucket rate limiter using Redis."""

import time
from typing import Optional

import redis.asyncio as aioredis

from celerlite.observability.logger import get_logger

logger = get_logger(__name__)

RATE_LIMIT_KEY = "celerlite:ratelimit:{task_name}"


class RateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(self, redis_client: aioredis.Redis):
        self._client = redis_client
        self._limits: dict[str, tuple[int, int]] = {}  # task_name → (max_rate, window_seconds)

    def configure(self, task_name: str, max_rate: int, window_seconds: int = 60) -> None:
        """Set rate limit for a task type."""
        self._limits[task_name] = (max_rate, window_seconds)
        logger.info(
            "rate_limit_configured",
            task=task_name,
            max_rate=max_rate,
            window=window_seconds,
        )

    async def acquire(self, task_name: str) -> bool:
        """
        Return True if the task can proceed (under rate limit), False if throttled.
        Uses a Redis sorted set with timestamps as scores for sliding window.
        """
        if task_name not in self._limits:
            return True  # No limit configured

        max_rate, window_seconds = self._limits[task_name]
        key = RATE_LIMIT_KEY.format(task_name=task_name)
        now = time.time()
        window_start = now - window_seconds

        pipe = self._client.pipeline()
        # Remove old entries outside the window
        pipe.zremrangebyscore(key, "-inf", window_start)
        # Count entries in the window
        pipe.zcard(key)
        # Add current timestamp
        pipe.zadd(key, {str(now): now})
        # Set TTL
        pipe.expire(key, window_seconds + 1)
        results = await pipe.execute()

        current_count = results[1]  # Before adding current
        if current_count >= max_rate:
            # Remove the just-added entry since we're throttling
            await self._client.zrem(key, str(now))
            logger.debug("rate_limited", task=task_name, count=current_count, limit=max_rate)
            return False

        return True

    async def get_current_rate(self, task_name: str) -> dict:
        """Return current rate usage for a task type."""
        if task_name not in self._limits:
            return {"configured": False}

        max_rate, window_seconds = self._limits[task_name]
        key = RATE_LIMIT_KEY.format(task_name=task_name)
        now = time.time()
        window_start = now - window_seconds

        count = await self._client.zcount(key, window_start, now)
        return {
            "task_name": task_name,
            "current_count": count,
            "max_rate": max_rate,
            "window_seconds": window_seconds,
            "utilization_pct": round((count / max_rate) * 100, 1) if max_rate > 0 else 0,
        }
