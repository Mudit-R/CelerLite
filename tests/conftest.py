"""Pytest fixtures shared across the test suite."""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from celerlite.broker.serializer import TaskMessage
from celerlite.config import CelerLiteConfig


@pytest.fixture
def test_config():
    return CelerLiteConfig(
        REDIS_URL="redis://localhost:6379/1",  # DB 1 for tests
        DATABASE_URL="sqlite+aiosqlite:///./test_celerlite.db",
        WORKER_CONCURRENCY=2,
        MAX_RETRIES=3,
        RETRY_BACKOFF_BASE=2.0,
        RETRY_BACKOFF_MAX=60.0,
        RETRY_JITTER=False,  # Deterministic for tests
        HEARTBEAT_INTERVAL=5,
        HEARTBEAT_TIMEOUT=15,
    )


@pytest.fixture
def sample_message():
    return TaskMessage(
        task_id="test-task-001",
        task_name="tests.tasks.add",
        args=[1, 2],
        kwargs={},
        queue="test",
        priority=1,
        retry_count=0,
        max_retries=3,
        timeout=30,
    )


@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.enqueue = AsyncMock(return_value="celerlite:queue:default:normal")
    broker.dequeue = AsyncMock(return_value=None)
    broker.acknowledge = AsyncMock()
    broker.reject = AsyncMock()
    broker.store_result = AsyncMock()
    broker.get_result = AsyncMock(return_value=None)
    broker.publish_event = AsyncMock()
    broker.mark_task_revoked = AsyncMock()
    broker.is_revoked = AsyncMock(return_value=False)
    return broker
