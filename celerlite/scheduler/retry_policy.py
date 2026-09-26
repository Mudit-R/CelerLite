"""Retry policy with exponential backoff + jitter and DLQ routing."""

import random
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from celerlite.broker.serializer import TaskMessage
from celerlite.config import CelerLiteConfig
from celerlite.observability.logger import get_logger

logger = get_logger(__name__)


class RetryableError(Exception):
    """Raise this to explicitly signal a retryable error."""


class FatalError(Exception):
    """Raise this to skip retries and immediately route to DLQ."""


@dataclass
class DLQEntry:
    task_id: str
    task_name: str
    args_json: str
    kwargs_json: str
    error_message: str
    error_traceback: str
    retry_count: int
    original_queue: str
    metadata_json: Optional[str] = None
    dead_lettered_at: Optional[str] = None


class RetryPolicy:
    """Decides whether to retry a failed task and calculates backoff delays."""

    def __init__(self, config: CelerLiteConfig):
        self.config = config

    def should_retry(self, message: TaskMessage, error: Exception) -> bool:
        """Return True if the task should be retried."""
        if isinstance(error, FatalError):
            return False
        return message.retry_count < message.max_retries

    def get_backoff_delay(self, retry_count: int) -> float:
        """Exponential backoff with optional full jitter."""
        delay = min(
            self.config.RETRY_BACKOFF_BASE ** retry_count,
            self.config.RETRY_BACKOFF_MAX,
        )
        if self.config.RETRY_JITTER:
            delay = delay * random.uniform(0.5, 1.5)
        return delay

    def prepare_retry(self, message: TaskMessage) -> TaskMessage:
        """Return a new TaskMessage with incremented retry_count and ETA."""
        delay = self.get_backoff_delay(message.retry_count)
        eta_ts = time.time() + delay
        eta_iso = datetime.fromtimestamp(eta_ts, tz=timezone.utc).isoformat()

        data = message.model_dump()
        data["retry_count"] = message.retry_count + 1
        data["eta"] = eta_iso

        logger.info(
            "task_retry_scheduled",
            task_id=message.task_id,
            retry_count=data["retry_count"],
            delay_seconds=round(delay, 2),
            eta=eta_iso,
        )
        return TaskMessage(**data)

    def build_dlq_entry(self, message: TaskMessage, error: Exception) -> DLQEntry:
        """Create a DLQ entry with full error context."""
        import json

        tb = traceback.format_exc()
        return DLQEntry(
            task_id=message.task_id,
            task_name=message.task_name,
            args_json=json.dumps(message.args),
            kwargs_json=json.dumps(message.kwargs),
            error_message=str(error),
            error_traceback=tb,
            retry_count=message.retry_count,
            original_queue=message.queue,
            metadata_json=json.dumps(message.metadata),
            dead_lettered_at=datetime.now(timezone.utc).isoformat(),
        )
