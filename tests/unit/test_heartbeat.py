"""Unit tests for worker heartbeat publisher and monitor."""

import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from celerlite.worker.heartbeat import HeartbeatPublisher, HeartbeatMonitor, HEARTBEAT_KEY


@pytest.mark.asyncio
class TestHeartbeatPublisher:
    async def test_beat_writes_fields_and_sets_ttl(self):
        mock_redis = AsyncMock()
        pipe = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[True] * 10)

        pub = HeartbeatPublisher("worker-1", mock_redis, ttl=40)
        await pub.beat(
            status="BUSY",
            current_task_id="task-123",
            tasks_processed=10,
            tasks_failed=1,
            pid=9999,
        )

        pipe.hset.assert_any_call("celerlite:heartbeat:worker-1", "worker_id", "worker-1")
        pipe.hset.assert_any_call("celerlite:heartbeat:worker-1", "status", "BUSY")
        pipe.hset.assert_any_call("celerlite:heartbeat:worker-1", "current_task_id", "task-123")
        pipe.hset.assert_any_call("celerlite:heartbeat:worker-1", "tasks_processed", "10")
        pipe.expire.assert_called_with("celerlite:heartbeat:worker-1", 40)
        pipe.execute.assert_called_once()

    async def test_clear_deletes_key(self):
        mock_redis = AsyncMock()
        pub = HeartbeatPublisher("worker-2", mock_redis)
        await pub.clear()
        mock_redis.delete.assert_called_once_with("celerlite:heartbeat:worker-2")


@pytest.mark.asyncio
class TestHeartbeatMonitor:
    async def test_get_stale_workers(self):
        mock_redis = AsyncMock()
        monitor = HeartbeatMonitor(mock_redis, heartbeat_timeout=30)

        # Fresh worker: 5 seconds ago
        fresh_time = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        # Stale worker: 60 seconds ago
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

        monitor.get_all_heartbeats = AsyncMock(return_value=[
            {"worker_id": "worker-alive", "last_heartbeat": fresh_time},
            {"worker_id": "worker-dead", "last_heartbeat": stale_time},
            {"worker_id": "worker-broken", "last_heartbeat": "invalid-timestamp"},
        ])

        stale = await monitor.get_stale_workers()
        assert "worker-dead" in stale
        assert "worker-broken" in stale
        assert "worker-alive" not in stale
