"""Unit tests for task message serialization."""

import pytest
from celerlite.broker.serializer import Serializer, TaskMessage, TaskResult


def make_message(**kwargs):
    defaults = dict(
        task_name="tests.add",
        args=[1, 2],
        kwargs={},
        queue="default",
        priority=1,
        retry_count=0,
        max_retries=3,
        timeout=300,
    )
    defaults.update(kwargs)
    return TaskMessage(**defaults)


class TestSerializer:
    def test_json_round_trip(self):
        msg = make_message()
        raw = Serializer.serialize(msg, fmt="json")
        restored = Serializer.deserialize(raw, fmt="json")
        assert restored.task_id == msg.task_id
        assert restored.task_name == msg.task_name
        assert restored.args == msg.args

    def test_msgpack_round_trip(self):
        msg = make_message()
        raw = Serializer.serialize(msg, fmt="msgpack")
        restored = Serializer.deserialize(raw, fmt="msgpack")
        assert restored.task_id == msg.task_id
        assert restored.args == [1, 2]

    def test_result_round_trip(self):
        result = TaskResult(task_id="abc", status="SUCCESS", result=42, duration_ms=1.5)
        raw = Serializer.serialize_result(result)
        restored = Serializer.deserialize_result(raw)
        assert restored.result == 42
        assert restored.status == "SUCCESS"

    def test_invalid_task_name_raises(self):
        with pytest.raises(Exception):
            TaskMessage(task_name="", args=[], kwargs={})

    def test_invalid_priority_raises(self):
        with pytest.raises(Exception):
            TaskMessage(task_name="test", args=[], kwargs={}, priority=99)

    def test_large_payload(self):
        big_args = list(range(10000))
        msg = make_message(args=big_args)
        raw = Serializer.serialize(msg)
        restored = Serializer.deserialize(raw)
        assert len(restored.args) == 10000

    def test_nested_kwargs(self):
        msg = make_message(kwargs={"nested": {"a": [1, 2, 3], "b": {"c": True}}})
        raw = Serializer.serialize(msg)
        restored = Serializer.deserialize(raw)
        assert restored.kwargs["nested"]["b"]["c"] is True
