"""Unit tests for InMemoryBroker."""

import pytest
from celerlite.broker.memory_broker import InMemoryBroker
from celerlite.config import CelerLiteConfig
from celerlite.scheduler.priority import Priority


@pytest.mark.asyncio
class TestInMemoryBroker:
    async def test_enqueue_and_strict_priority_dequeue(self):
        cfg = CelerLiteConfig()
        broker = InMemoryBroker(cfg)
        await broker.connect()

        # Enqueue in reverse priority order
        await broker.enqueue("test_q", b"low_task", priority=Priority.LOW)
        await broker.enqueue("test_q", b"normal_task", priority=Priority.NORMAL)
        await broker.enqueue("test_q", b"critical_task", priority=Priority.CRITICAL)
        await broker.enqueue("test_q", b"high_task", priority=Priority.HIGH)

        # Dequeue must respect strict priority: CRITICAL -> HIGH -> NORMAL -> LOW
        msg1 = await broker.dequeue("test_q", timeout=1)
        assert msg1 == b"critical_task"

        msg2 = await broker.dequeue("test_q", timeout=1)
        assert msg2 == b"high_task"

        msg3 = await broker.dequeue("test_q", timeout=1)
        assert msg3 == b"normal_task"

        msg4 = await broker.dequeue("test_q", timeout=1)
        assert msg4 == b"low_task"

        # Acknowledge all
        for m in [msg1, msg2, msg3, msg4]:
            await broker.acknowledge("test_q", m)

        assert len(broker._processing["test_q"]) == 0
        await broker.disconnect()

    async def test_store_and_get_result(self):
        cfg = CelerLiteConfig()
        broker = InMemoryBroker(cfg)
        await broker.connect()

        await broker.store_result("task-123", b"result_data", ttl=100)
        res = await broker.get_result("task-123")
        assert res == b"result_data"

        missing = await broker.get_result("unknown-id")
        assert missing is None
        await broker.disconnect()

    async def test_revocation(self):
        cfg = CelerLiteConfig()
        broker = InMemoryBroker(cfg)
        await broker.connect()

        assert await broker.is_revoked("rev-1") is False
        await broker.mark_task_revoked("rev-1")
        assert await broker.is_revoked("rev-1") is True
        await broker.disconnect()
