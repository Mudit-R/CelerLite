from unittest.mock import AsyncMock

import pytest

from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.config import CelerLiteConfig
from celerlite.scheduler.retry_policy import FatalError
from celerlite.worker.worker import Worker


@pytest.fixture
def worker():
    worker = Worker('test-worker', CelerLiteConfig(RETRY_JITTER=False))
    worker._broker = AsyncMock()
    worker._update_task_status = AsyncMock()
    worker._save_to_dlq = AsyncMock()
    return worker


async def test_failed_task_replaced_with_incremented_retry(worker):
    message = TaskMessage(task_name='test', retry_count=0, max_retries=2, priority=2)
    raw = Serializer.serialize(message)
    worker._broker.replace_reserved.return_value = True
    await worker._handle_failure(message, raw, RuntimeError('temporary'))
    args = worker._broker.replace_reserved.await_args.args
    assert args[0:2] == ('default', raw)
    retry = Serializer.deserialize(args[2])
    assert retry.retry_count == 1 and retry.eta is not None and args[3] == 2
    worker._broker.acknowledge.assert_not_awaited()
    worker._broker.enqueue.assert_not_awaited()


async def test_dlq_failure_does_not_acknowledge_task(worker):
    message = TaskMessage(task_name='test', max_retries=0)
    raw = Serializer.serialize(message)
    worker._save_to_dlq.side_effect = RuntimeError('database unavailable')
    with pytest.raises(RuntimeError, match='database unavailable'):
        await worker._handle_failure(message, raw, FatalError('invalid task'))
    worker._broker.acknowledge.assert_not_awaited()


async def test_dlq_is_saved_before_acknowledgement(worker):
    message = TaskMessage(task_name='test', max_retries=0)
    raw = Serializer.serialize(message)
    events = []
    worker._save_to_dlq.side_effect = lambda entry: events.append('saved')
    worker._broker.acknowledge.side_effect = lambda *args: events.append('acknowledged')
    await worker._handle_failure(message, raw, FatalError('invalid task'))
    assert events == ['saved', 'acknowledged']
