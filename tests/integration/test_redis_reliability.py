"""Real Redis integration checks. Set CELERLITE_TEST_REDIS_URL to enable.

Each test uses its own queue; no FLUSHDB or application data is touched.
"""
import asyncio
import os
import subprocess
import sys
import uuid

import pytest
import pytest_asyncio

from celerlite.broker.redis_broker import (
    LEGACY_PROCESSING_KEY,
    LEGACY_TIMESTAMP_KEY,
    PROCESSING_KEY,
    RESULT_KEY,
    TASK_TIMESTAMP_KEY,
    RedisBroker,
)
from celerlite.config import CelerLiteConfig
from celerlite.scheduler.priority import Priority, get_priority_queue_name
from celerlite.worker.pool import WorkerPool


@pytest_asyncio.fixture
async def real_queue():
    url = os.getenv('CELERLITE_TEST_REDIS_URL')
    if not url:
        pytest.skip('Set CELERLITE_TEST_REDIS_URL for real Redis integration tests')
    broker = RedisBroker(CelerLiteConfig(REDIS_URL=url))
    await broker.connect()  # Explicitly requested integration tests fail if unavailable.
    queue = 'integration-' + uuid.uuid4().hex
    try:
        yield broker, queue
    finally:
        keys = [key async for key in broker.client.scan_iter(match=f'celerlite:*:{queue}:*')]
        if keys:
            await broker.client.delete(*keys)
        await broker.disconnect()


@pytest.mark.parametrize('priority', list(Priority))
async def test_arriving_work_wakes_waiter_at_every_priority(real_queue, priority):
    broker, queue = real_queue
    waiter = asyncio.create_task(broker.dequeue(queue, timeout=2))
    await asyncio.sleep(0.1)
    await broker.enqueue(queue, b'arriving', priority)
    delivery = await asyncio.wait_for(waiter, timeout=0.8)
    assert delivery == b'arriving'
    timestamp_key = TASK_TIMESTAMP_KEY.format(queue=queue, priority=priority.name.lower())
    assert await broker.client.hget(timestamp_key, delivery.receipt + delivery)


async def test_strict_priority_and_fifo(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'low', Priority.LOW)
    await broker.enqueue(queue, b'first', Priority.HIGH)
    await broker.enqueue(queue, b'second', Priority.HIGH)
    assert [await broker.dequeue(queue, 1) for _ in range(3)] == [b'first', b'second', b'low']


async def test_pool_recovers_expired_reservation_and_preserves_renewed_one(real_queue, monkeypatch):
    broker, queue = real_queue
    monkeypatch.setenv('CELERLITE_WORKER_QUEUES', queue)
    pool = WorkerPool(broker.config.model_copy(update={'HEARTBEAT_TIMEOUT': 1}))
    await broker.enqueue(queue, b'crashed', Priority.HIGH)
    await broker.enqueue(queue, b'active', Priority.HIGH)
    crashed = await broker.dequeue(queue, 1)
    active = await broker.dequeue(queue, 1)
    key = TASK_TIMESTAMP_KEY.format(queue=queue, priority='high')
    await broker.client.hset(key, mapping={crashed.receipt + crashed: 0, active.receipt + active: 0})

    assert await broker.renew_reservation(queue, active)
    await pool._recover_stale_tasks()
    recovered = await broker.dequeue(queue, 1)
    assert recovered == crashed
    assert recovered.receipt != crashed.receipt
    assert not await broker.renew_reservation(queue, crashed)
    assert await broker.acknowledge(queue, active)
    assert await broker.acknowledge(queue, recovered)


async def test_concurrent_consumers_reserve_each_message_once(real_queue):
    broker, queue = real_queue
    messages = [str(i).encode() for i in range(100)]
    for message in messages:
        await broker.enqueue(queue, message)
    async def consume_batch():
        return [await broker.dequeue(queue, 2) for _ in range(10)]
    batches = await asyncio.gather(*(consume_batch() for _ in range(10)))
    received = [message for batch in batches for message in batch]
    assert set(received) == set(messages)
    assert len(received) == len(set(received))
    assert await broker.recover_stale_tasks(queue, 60) == 0


async def test_atomic_recovery_does_not_duplicate_messages(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'retry-me', Priority.HIGH)
    assert await broker.dequeue(queue, 1) == b'retry-me'
    recovered = await asyncio.gather(*(broker.recover_stale_tasks(queue, 0) for _ in range(8)))
    assert sum(recovered) == 1
    assert await broker.client.llen(get_priority_queue_name(queue, Priority.HIGH)) == 1
    delivery = await broker.dequeue(queue, 1)
    assert delivery == b'retry-me'
    assert await broker.acknowledge(queue, delivery)
    assert await broker.recover_stale_tasks(queue, 0) == 0


async def test_reject_preserves_priority_and_cannot_create_unreserved_work(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'important', Priority.CRITICAL)
    delivery = await broker.dequeue(queue, 1)
    assert await broker.reject(queue, delivery, requeue=True)
    assert not await broker.reject(queue, b'unknown', requeue=True)
    assert await broker.client.lrange(get_priority_queue_name(queue, Priority.CRITICAL), 0, -1) == [b'important']
    assert await broker.client.llen(get_priority_queue_name(queue, Priority.NORMAL)) == 0
    delivery = await broker.dequeue(queue, 1)
    assert await broker.reject(queue, delivery, requeue=False)
    assert await broker.recover_stale_tasks(queue, 0) == 0


async def test_timeout_and_cancellation(real_queue):
    broker, queue = real_queue
    assert await broker.dequeue(queue, 0.1) is None
    waiter = asyncio.create_task(broker.dequeue(queue, 0))
    await asyncio.sleep(0.1)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter


async def test_retry_payload_replacement_is_atomic_and_preserves_priority(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'attempt-1', Priority.HIGH)
    delivery = await broker.dequeue(queue, 1)
    assert delivery == b'attempt-1'
    assert await broker.replace_reserved(queue, delivery, b'attempt-2', Priority.HIGH)
    assert not await broker.replace_reserved(queue, delivery, b'attempt-2', Priority.HIGH)
    assert await broker.recover_stale_tasks(queue, 0) == 0
    assert await broker.client.lrange(get_priority_queue_name(queue, Priority.HIGH), 0, -1) == [b'attempt-2']
    retry = await broker.dequeue(queue, 1)
    assert retry == b'attempt-2'
    assert await broker.acknowledge(queue, retry)


async def test_retry_after_recovery_cannot_duplicate_queue_entry(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'attempt-1', Priority.NORMAL)
    delivery = await broker.dequeue(queue, 1)
    assert await broker.recover_stale_tasks(queue, 0) == 1
    assert not await broker.replace_reserved(queue, delivery, b'attempt-2', Priority.NORMAL)
    assert await broker.client.lrange(get_priority_queue_name(queue, Priority.NORMAL), 0, -1) == [b'attempt-1']


async def test_reassigned_delivery_cannot_be_finished_by_stale_worker(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'\x00same-payload', Priority.HIGH)
    stale = await broker.dequeue(queue, 1)
    assert await broker.recover_stale_tasks(queue, 0) == 1
    current = await broker.dequeue(queue, 1)
    assert stale == current == b'\x00same-payload'

    assert not await broker.acknowledge(queue, stale)
    assert not await broker.reject(queue, stale)
    assert not await broker.replace_reserved(queue, stale, b'stale-retry', Priority.HIGH)
    assert not await broker.acknowledge(queue, bytes(current))

    try:
        assert not await broker.complete_reserved(queue, stale, queue, b'stale-result', 60)
        assert await broker.get_result(queue) is None
        assert await broker.complete_reserved(queue, current, queue, b'current-result', 60)
        assert not await broker.complete_reserved(queue, stale, queue, b'stale-result', 60)
        assert await broker.get_result(queue) == b'current-result'
        assert await broker.recover_stale_tasks(queue, 0) == 0
        assert (await broker.get_queue_length(queue))['high'] == 0
    finally:
        await broker.client.delete(RESULT_KEY.format(task_id=queue))


async def test_identical_payloads_have_separate_active_reservations(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'duplicate')
    await broker.enqueue(queue, b'duplicate')
    first = await broker.dequeue(queue, 1)
    second = await broker.dequeue(queue, 1)
    assert first == second == b'duplicate'
    assert await broker.acknowledge(queue, first)
    assert not await broker.acknowledge(queue, first)
    assert await broker.acknowledge(queue, second)
    assert await broker.recover_stale_tasks(queue, 0) == 0


async def test_legacy_in_flight_messages_recover_without_changing_payload(real_queue):
    broker, queue = real_queue
    payload = b'legacy-\x00-payload'
    await broker.client.lpush(LEGACY_PROCESSING_KEY.format(queue=queue, priority='low'), payload)
    await broker.client.hset(LEGACY_TIMESTAMP_KEY.format(queue=queue, priority='low'), payload, 1)
    assert await broker.recover_stale_tasks(queue, 0) == 1
    delivery = await broker.dequeue(queue, 1)
    assert delivery == payload
    assert await broker.acknowledge(queue, delivery)


async def test_real_process_death_retains_reserved_work(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'crashed-process')
    code = '''
import asyncio, sys
from celerlite.broker.redis_broker import RedisBroker
from celerlite.config import CelerLiteConfig
async def main():
    broker = RedisBroker(CelerLiteConfig(REDIS_URL=sys.argv[1]))
    await broker.connect()
    assert await broker.dequeue(sys.argv[2], 2) == b'crashed-process'
    await asyncio.sleep(60)
asyncio.run(main())
'''
    proc = subprocess.Popen([sys.executable, '-c', code, broker.config.REDIS_URL, queue],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        key = PROCESSING_KEY.format(queue=queue, priority='normal')
        for _ in range(100):
            if await broker.client.llen(key):
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail('Child process did not reserve a task')
        proc.kill()
        await asyncio.to_thread(proc.wait, timeout=5)
        assert await broker.recover_stale_tasks(queue, 0) == 1
        delivery = await broker.dequeue(queue, 1)
        assert delivery == b'crashed-process'
        assert await broker.acknowledge(queue, delivery)
        assert await broker.recover_stale_tasks(queue, 0) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
