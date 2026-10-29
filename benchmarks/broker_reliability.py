"""Measured real-Redis broker workload, not end-to-end user-task throughput.

python -m benchmarks.broker_reliability --redis-url redis://localhost:6379/15 --tasks 10000 --output broker_results.json
Uses an isolated UUID queue and deletes only that queue's test keys.
"""
import argparse
import asyncio
import json
import platform
import time
import uuid
from pathlib import Path

from celerlite.broker.redis_broker import RedisBroker
from celerlite.config import CelerLiteConfig
from celerlite.scheduler.priority import Priority, get_priority_queue_name


async def run(args):
    broker = RedisBroker(CelerLiteConfig(REDIS_URL=args.redis_url))
    await broker.connect()
    queue = 'benchmark-' + uuid.uuid4().hex
    try:
        messages = [f'job-{i}'.encode() for i in range(args.tasks)]
        pipe = broker.client.pipeline(transaction=False)
        for message in messages:
            pipe.lpush(get_priority_queue_name(queue, Priority.NORMAL), message)
        await pipe.execute()
        started = time.perf_counter()
        async def consumer(count):
            received = []
            for _ in range(count):
                message = await broker.dequeue(queue, timeout=5)
                if message is None:
                    raise RuntimeError('Timed out before all messages were consumed')
                await broker.acknowledge(queue, message)
                received.append(message)
            return received
        batches = await asyncio.gather(*(consumer(args.tasks // args.consumers + (i < args.tasks % args.consumers))
                                         for i in range(args.consumers)))
        seconds = time.perf_counter() - started
        received = [m for batch in batches for m in batch]
        assert len(received) == args.tasks and set(received) == set(messages)
        assert sum((await broker.get_queue_length(queue)).values()) == 0
        assert await broker.recover_stale_tasks(queue, 0) == 0
        result = {'workload': 'Redis broker reserve-and-ack; no user task execution or DB persistence',
                  'tasks': args.tasks, 'consumers': args.consumers,
                  'completed_unique': len(set(received)), 'missing': len(set(messages)-set(received)),
                  'duplicates': len(received)-len(set(received)),
                  'seconds': round(seconds, 3), 'messages_per_second': round(args.tasks/seconds, 1),
                  'python': platform.python_version(), 'platform': platform.platform(),
                  'redis_version': (await broker.client.info('server'))['redis_version']}
        Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        keys = [key async for key in broker.client.scan_iter(match=f'celerlite:*:{queue}:*')]
        if keys:
            await broker.client.delete(*keys)
        await broker.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--redis-url', default='redis://localhost:6379/15')
    parser.add_argument('--tasks', type=int, default=10000)
    parser.add_argument('--consumers', type=int, default=10)
    parser.add_argument('--output', default='broker_results.json')
    args = parser.parse_args()
    if args.tasks < 1 or not 1 <= args.consumers <= 10:
        parser.error('tasks must be positive; consumers must be between 1 and 10')
    asyncio.run(run(args))
