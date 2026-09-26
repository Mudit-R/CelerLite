"""System metrics endpoint."""

from fastapi import APIRouter, Depends

from celerlite.api.app import get_broker
from celerlite.broker.redis_broker import RedisBroker
from celerlite.config import config
from celerlite.observability.metrics import metrics
from celerlite.persistence.database import get_session
from celerlite.persistence.repository import TaskRepository
from celerlite.worker.heartbeat import HeartbeatMonitor

router = APIRouter()


@router.get("")
async def get_metrics(broker: RedisBroker = Depends(get_broker)):
    """Comprehensive system metrics snapshot."""
    snapshot = metrics.get_snapshot()

    # DB counts
    async with get_session() as session:
        repo = TaskRepository(session)
        counts = await repo.get_counts_by_status()

    # Worker heartbeats
    monitor = HeartbeatMonitor(broker.client, config.HEARTBEAT_TIMEOUT)
    heartbeats = await monitor.get_all_heartbeats()
    stale = await monitor.get_stale_workers()

    # Redis info
    try:
        redis_info = await broker.get_redis_info()
    except Exception:
        redis_info = {"connected": False, "memory_used_mb": 0}

    # Queue lengths for common queues
    queue_lengths = await broker.get_all_queue_lengths(["default", "emails", "high_priority"])

    return {
        "uptime_seconds": snapshot["uptime_seconds"],
        "tasks": {
            "submitted_total": snapshot["submitted_total"],
            "completed_total": snapshot["completed_total"],
            "failed_total": snapshot["failed_total"],
            "dead_lettered_total": snapshot["dead_lettered_total"],
            "throughput_per_sec": snapshot["throughput_per_sec"],
            "avg_latency_ms": snapshot["avg_latency_ms"],
            "p99_latency_ms": snapshot["p99_latency_ms"],
            "by_status": counts,
        },
        "queues": queue_lengths,
        "workers": {
            "total": len(heartbeats),
            "active": len(heartbeats) - len(stale),
            "dead": len(stale),
        },
        "redis": redis_info,
    }
