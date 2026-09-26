"""Priority levels for task queuing."""

from enum import IntEnum


class Priority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


PRIORITY_SUFFIX = {
    Priority.LOW: "low",
    Priority.NORMAL: "normal",
    Priority.HIGH: "high",
    Priority.CRITICAL: "critical",
}


def get_priority_queue_name(base_queue: str, priority: Priority) -> str:
    """Return the Redis key for a given queue + priority."""
    suffix = PRIORITY_SUFFIX[priority]
    return f"celerlite:queue:{base_queue}:{suffix}"


def get_priority_dequeue_order(base_queue: str) -> list[str]:
    """Return queue names in strict priority order (critical first)."""
    return [
        get_priority_queue_name(base_queue, Priority.CRITICAL),
        get_priority_queue_name(base_queue, Priority.HIGH),
        get_priority_queue_name(base_queue, Priority.NORMAL),
        get_priority_queue_name(base_queue, Priority.LOW),
    ]
