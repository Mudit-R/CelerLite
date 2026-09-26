"""Unit tests for database models and schema definitions."""

import json
import pytest
from datetime import datetime, timezone
from celerlite.persistence.models import Base, TaskModel, WorkerModel, DLQEntry, utcnow


class TestModels:
    def test_task_model_defaults(self):
        task = TaskModel(
            task_name="tasks.send_email",
            args_json=json.dumps(["user@example.com"]),
            kwargs_json=json.dumps({"subject": "Welcome"}),
        )
        assert task.id is not None
        assert len(task.id) == 36
        assert task.status == "PENDING"
        assert task.queue == "default"
        assert task.priority == 1
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert task.worker_id is None
        assert task.started_at is None
        assert task.completed_at is None
        assert task.timeout == 300

    def test_worker_model_defaults(self):
        worker = WorkerModel(
            id="worker-host-1",
            pid=1234,
            hostname="worker-node-1",
        )
        assert worker.id == "worker-host-1"
        assert worker.pid == 1234
        assert worker.status == "ONLINE"
        assert worker.tasks_processed == 0
        assert worker.tasks_failed == 0
        assert worker.current_task_id is None

    def test_dlq_entry_defaults(self):
        dlq = DLQEntry(
            task_id="abc-123",
            task_name="tasks.charge_card",
            args_json="[100]",
            kwargs_json="{}",
            error_message="Card expired",
            error_traceback="Traceback ...",
            retry_count=3,
            original_queue="payments",
        )
        assert dlq.id is not None
        assert dlq.task_id == "abc-123"
        assert dlq.task_name == "tasks.charge_card"
        assert dlq.replayed is False
        assert dlq.replayed_at is None
        assert dlq.original_queue == "payments"

    def test_utcnow_is_timezone_aware(self):
        dt = utcnow()
        assert dt.tzinfo is not None
        assert dt.tzinfo == timezone.utc
