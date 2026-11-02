from collections import defaultdict, deque
from unittest.mock import AsyncMock

import pytest

from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.worker.worker import WORKER_QUEUES, Worker, register_task


class QueueBroker:
    def __init__(self, messages=None):
        self.messages = defaultdict(deque)
        for queue_name, payloads in (messages or {}).items():
            self.messages[queue_name].extend(payloads)
        self.polled = []
        self.acknowledged = []
        self.results = []

    async def dequeue(self, queue_name, timeout):
        self.polled.append(queue_name)
        if self.messages[queue_name]:
            return self.messages[queue_name].popleft()
        return None

    async def acknowledge(self, queue_name, raw):
        self.acknowledged.append((queue_name, raw))

    async def is_revoked(self, task_id):
        return False

    async def publish_event(self, event):
        return None

    async def store_result(self, task_id, result, ttl):
        self.results.append((task_id, result, ttl))


def task_payload(queue_name, *, task_name="tests.worker_queues.noop", **kwargs):
    message = TaskMessage(task_name=task_name, queue=queue_name, **kwargs)
    return Serializer.serialize(message)


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_name", WORKER_QUEUES)
async def test_worker_processes_and_acknowledges_every_configured_queue(queue_name):
    register_task("tests.worker_queues.noop", lambda: "finished")
    worker = Worker("queue-test")
    raw = task_payload(queue_name)
    broker = QueueBroker({queue_name: [raw]})
    worker._broker = broker
    worker._update_task_status = AsyncMock()

    await worker._process_one()

    assert broker.acknowledged == [(queue_name, raw)]
    assert broker.results[0][0] == Serializer.deserialize(raw).task_id
    assert worker._tasks_processed == 1


@pytest.mark.asyncio
async def test_round_robin_polling_gives_crm_queue_a_turn_while_default_is_busy():
    register_task("tests.worker_queues.noop", lambda: "finished")
    worker = Worker("fairness-test")
    default_raw = task_payload("default")
    crm_raw = task_payload("crm")
    broker = QueueBroker({"default": [default_raw, default_raw], "crm": [crm_raw]})
    worker._broker = broker
    worker._update_task_status = AsyncMock()

    await worker._process_one()
    await worker._process_one()

    assert broker.acknowledged == [("default", default_raw), ("crm", crm_raw)]


@pytest.mark.asyncio
async def test_malformed_message_is_acknowledged_from_the_queue_it_was_reserved_from():
    worker = Worker("malformed-test")
    broker = QueueBroker({"analytics": [b"not-json"]})
    worker._broker = broker

    await worker._process_one()

    assert broker.acknowledged == [("analytics", b"not-json")]


@pytest.mark.asyncio
async def test_worker_can_consume_custom_sdk_queues_from_environment(monkeypatch):
    monkeypatch.setenv("CELERLITE_WORKER_QUEUES", "reports,crm,reports")
    register_task("tests.worker_queues.noop", lambda: "finished")
    worker = Worker("custom-queue-test")
    raw = task_payload("reports")
    broker = QueueBroker({"reports": [raw]})
    worker._broker = broker
    worker._update_task_status = AsyncMock()

    await worker._process_one()

    assert worker._queues == ("reports", "crm")
    assert broker.acknowledged == [("reports", raw)]


@pytest.mark.asyncio
async def test_retry_replaces_the_reservation_in_the_original_queue():
    worker = Worker("retry-test")
    worker._broker = AsyncMock()
    worker._broker.replace_reserved.return_value = True
    worker._update_task_status = AsyncMock()
    message = TaskMessage(task_name="tests.worker_queues.fails", queue="crm", max_retries=2)
    raw = Serializer.serialize(message)

    await worker._handle_failure(message, raw, RuntimeError("retry me"), queue_name="crm")

    args = worker._broker.replace_reserved.await_args.args
    assert args[0] == "crm"
    assert args[1] == raw
