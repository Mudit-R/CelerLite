"""Exercise standalone execution through the actual in-memory broker."""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from celerlite.broker.memory_broker import InMemoryBroker
from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.config import CelerLiteConfig
from celerlite.worker import embedded


@pytest.mark.parametrize('name,args,expected', [
    ('celerlite.demo.add', [20, 22], 'SUCCESS'),
    ('unregistered.add.task', [20, 22], 'FAILED'),
])
async def test_registered_and_unknown_tasks_are_reported_accurately(monkeypatch, name, args, expected):
    broker = InMemoryBroker(CelerLiteConfig())
    stop = asyncio.Event()
    statuses = []

    @asynccontextmanager
    async def session():
        yield object()

    class TaskRepo:
        def __init__(self, _session):
            pass
        async def update_status(self, task_id, status, **kwargs):
            statuses.append((status, kwargs))
            if status in ('SUCCESS', 'FAILED'):
                stop.set()

    monkeypatch.setattr(embedded, 'get_session', session)
    monkeypatch.setattr(embedded, 'TaskRepository', TaskRepo)
    monkeypatch.setattr(embedded, 'WorkerRepository', lambda _: AsyncMock())
    message = TaskMessage(task_name=name, args=args)
    await broker.enqueue('default', Serializer.serialize(message))
    await asyncio.wait_for(embedded.run_embedded_worker(broker, stop_event=stop), timeout=5)
    result = Serializer.deserialize_result(await broker.get_result(message.task_id))
    assert result.status == expected
    assert statuses[-1][0] == expected
    if expected == 'SUCCESS':
        assert result.result == 42
    else:
        assert 'Task not registered' in result.error
