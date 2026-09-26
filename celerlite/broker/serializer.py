"""Serialization layer for task messages (JSON + msgpack)."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import msgpack
from pydantic import BaseModel, Field, field_validator


class TaskMessage(BaseModel):
    """Validated task message passed through the broker."""

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_name: str
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    queue: str = "default"
    priority: int = 1  # Priority enum value
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = 300
    eta: Optional[str] = None  # ISO 8601 datetime string
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    revoked: bool = False

    @field_validator("task_name")
    @classmethod
    def task_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task_name must not be empty")
        return v

    @field_validator("priority")
    @classmethod
    def priority_valid(cls, v: int) -> int:
        if v not in (0, 1, 2, 3):
            raise ValueError("priority must be 0 (LOW), 1 (NORMAL), 2 (HIGH), or 3 (CRITICAL)")
        return v


class TaskResult(BaseModel):
    """Result of a completed task."""

    task_id: str
    status: str  # SUCCESS | FAILED | REVOKED
    result: Any = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    duration_ms: Optional[float] = None
    completed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _default_json(obj: Any) -> Any:
    """JSON encoder for non-serializable types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class Serializer:
    """Serialize/deserialize task messages and results."""

    @staticmethod
    def serialize(message: TaskMessage, fmt: str = "json") -> bytes:
        data = message.model_dump()
        if fmt == "msgpack":
            return msgpack.packb(data, use_bin_type=True)
        return json.dumps(data, default=_default_json).encode("utf-8")

    @staticmethod
    def deserialize(data: bytes, fmt: str = "json") -> TaskMessage:
        if fmt == "msgpack":
            raw = msgpack.unpackb(data, raw=False)
        else:
            raw = json.loads(data.decode("utf-8"))
        return TaskMessage(**raw)

    @staticmethod
    def serialize_result(result: TaskResult, fmt: str = "json") -> bytes:
        data = result.model_dump()
        if fmt == "msgpack":
            return msgpack.packb(data, use_bin_type=True)
        return json.dumps(data, default=_default_json).encode("utf-8")

    @staticmethod
    def deserialize_result(data: bytes, fmt: str = "json") -> TaskResult:
        if fmt == "msgpack":
            raw = msgpack.unpackb(data, raw=False)
        else:
            raw = json.loads(data.decode("utf-8"))
        return TaskResult(**raw)
