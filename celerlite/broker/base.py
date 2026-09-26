"""Abstract broker interface."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class BaseBroker(ABC):
    """Abstract base for message brokers. Allows swapping Redis for other backends."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection gracefully."""

    @abstractmethod
    async def enqueue(self, queue_name: str, message: bytes, priority: int = 1) -> str:
        """Enqueue a serialized task message. Returns queue key used."""

    @abstractmethod
    async def dequeue(self, queue_name: str, timeout: int = 5) -> Optional[bytes]:
        """Blocking dequeue across all priority sub-queues. Returns raw bytes or None."""

    @abstractmethod
    async def acknowledge(self, queue_name: str, raw_message: bytes) -> None:
        """Acknowledge successful processing — remove from processing queue."""

    @abstractmethod
    async def reject(self, queue_name: str, raw_message: bytes, requeue: bool = True) -> None:
        """Reject a message — requeue or discard."""

    @abstractmethod
    async def store_result(self, task_id: str, result: bytes, ttl: int = 86400) -> None:
        """Persist a task result with TTL."""

    @abstractmethod
    async def get_result(self, task_id: str) -> Optional[bytes]:
        """Retrieve a stored task result."""

    @abstractmethod
    async def get_queue_length(self, queue_name: str) -> dict[str, int]:
        """Return pending message counts per priority sub-queue."""

    @abstractmethod
    async def publish_event(self, event: dict) -> None:
        """Publish a lifecycle event to the real-time pub/sub channel."""

    @abstractmethod
    async def recover_stale_tasks(self, queue_name: str, timeout_seconds: int = 30) -> int:
        """Move tasks stuck in the processing queue back to pending. Returns count recovered."""
