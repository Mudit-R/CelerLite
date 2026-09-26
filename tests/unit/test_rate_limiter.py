"""Unit tests for the sliding-window RateLimiter."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from celerlite.scheduler.rate_limiter import RateLimiter, RATE_LIMIT_KEY


@pytest.mark.asyncio
class TestRateLimiter:
    async def test_no_limit_configured_returns_true(self):
        mock_redis = AsyncMock()
        limiter = RateLimiter(mock_redis)
        # Should allow execution without redis calls
        allowed = await limiter.acquire("tasks.unlimited")
        assert allowed is True
        mock_redis.pipeline.assert_not_called()

    async def test_under_rate_limit_allows(self):
        mock_redis = AsyncMock()
        pipe = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        # pipeline execute returns [zremrangebyscore_res, zcard_res, zadd_res, expire_res]
        # current_count is index 1, say 2 out of limit 5
        pipe.execute = AsyncMock(return_value=[0, 2, 1, True])

        limiter = RateLimiter(mock_redis)
        limiter.configure("tasks.api_call", max_rate=5, window_seconds=60)

        allowed = await limiter.acquire("tasks.api_call")
        assert allowed is True
        pipe.zremrangebyscore.assert_called_once()
        pipe.zcard.assert_called_once()
        pipe.zadd.assert_called_once()

    async def test_exceeding_rate_limit_throttles(self):
        mock_redis = AsyncMock()
        pipe = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        # current_count is 5 (limit is 5)
        pipe.execute = AsyncMock(return_value=[0, 5, 1, True])

        limiter = RateLimiter(mock_redis)
        limiter.configure("tasks.api_call", max_rate=5, window_seconds=60)

        allowed = await limiter.acquire("tasks.api_call")
        assert allowed is False
        # Should clean up the just-added token
        mock_redis.zrem.assert_called_once()

    async def test_get_current_rate_unconfigured(self):
        mock_redis = AsyncMock()
        limiter = RateLimiter(mock_redis)
        rate = await limiter.get_current_rate("unknown")
        assert rate == {"configured": False}

    async def test_get_current_rate_configured(self):
        mock_redis = AsyncMock()
        mock_redis.zcount = AsyncMock(return_value=3)

        limiter = RateLimiter(mock_redis)
        limiter.configure("tasks.heavy", max_rate=10, window_seconds=30)
        rate = await limiter.get_current_rate("tasks.heavy")

        assert rate["task_name"] == "tasks.heavy"
        assert rate["current_count"] == 3
        assert rate["max_rate"] == 10
        assert rate["window_seconds"] == 30
        assert rate["utilization_pct"] == 30.0
