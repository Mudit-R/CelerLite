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

from celerlite.broker.redis_broker import RedisBroker, PROCESSING_KEY, TASK_TIMESTAMP_KEY
from celerlite.config import CelerLiteConfig
from celerlite.scheduler.priority import Priority, get_priority_queue_name


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
    assert await asyncio.wait_for(waiter, timeout=0.8) == b'arriving'
    assert await broker.client.hget(TASK_TIMESTAMP_KEY.format(queue=queue, priority=priority.name.lower()), b'arriving')


async def test_strict_priority_and_fifo(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'low', Priority.LOW)
    await broker.enqueue(queue, b'first', Priority.HIGH)
    await broker.enqueue(queue, b'second', Priority.HIGH)
    assert [await broker.dequeue(queue, 1) for _ in range(3)] == [b'first', b'second', b'low']


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
    assert await broker.dequeue(queue, 1) == b'retry-me'
    await broker.acknowledge(queue, b'retry-me')
    assert await broker.recover_stale_tasks(queue, 0) == 0


async def test_reject_preserves_priority_and_cannot_create_unreserved_work(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'important', Priority.CRITICAL)
    await broker.dequeue(queue, 1)
    await broker.reject(queue, b'important', requeue=True)
    await broker.reject(queue, b'unknown', requeue=True)
    assert await broker.client.lrange(get_priority_queue_name(queue, Priority.CRITICAL), 0, -1) == [b'important']
    assert await broker.client.llen(get_priority_queue_name(queue, Priority.NORMAL)) == 0
    await broker.dequeue(queue, 1)
    await broker.reject(queue, b'important', requeue=False)
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
    assert await broker.dequeue(queue, 1) == b'attempt-1'
    assert await broker.replace_reserved(queue, b'attempt-1', b'attempt-2', Priority.HIGH)
    assert not await broker.replace_reserved(queue, b'attempt-1', b'attempt-2', Priority.HIGH)
    assert await broker.recover_stale_tasks(queue, 0) == 0
    assert await broker.client.lrange(get_priority_queue_name(queue, Priority.HIGH), 0, -1) == [b'attempt-2']
    assert await broker.dequeue(queue, 1) == b'attempt-2'
    await broker.acknowledge(queue, b'attempt-2')


async def test_retry_after_recovery_cannot_duplicate_queue_entry(real_queue):
    broker, queue = real_queue
    await broker.enqueue(queue, b'attempt-1', Priority.NORMAL)
    await broker.dequeue(queue, 1)
    assert await broker.recover_stale_tasks(queue, 0) == 1
    assert not await broker.replace_reserved(queue, b'attempt-1', b'attempt-2', Priority.NORMAL)
    assert await broker.client.lrange(get_priority_queue_name(queue, Priority.NORMAL), 0, -1) == [b'attempt-1']


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
        assert await broker.dequeue(queue, 1) == b'crashed-process'
        await broker.acknowledge(queue, b'crashed-process')
        assert await broker.recover_stale_tasks(queue, 0) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
