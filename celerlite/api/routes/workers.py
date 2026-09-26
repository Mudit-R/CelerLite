"""Worker monitoring API routes."""

from fastapi import APIRouter, Depends

from celerlite.api.app import get_broker
from celerlite.broker.redis_broker import RedisBroker
from celerlite.persistence.database import get_session
from celerlite.persistence.repository import WorkerRepository
from celerlite.worker.heartbeat import HeartbeatMonitor
from celerlite.config import config

router = APIRouter()


@router.get("")
async def list_workers(broker: RedisBroker = Depends(get_broker)):
    """List all workers with live heartbeat data."""
    monitor = HeartbeatMonitor(broker.client, config.HEARTBEAT_TIMEOUT)
    heartbeats = await monitor.get_all_heartbeats()
    stale = await monitor.get_stale_workers()
    stale_set = set(stale)

    result = []
    for hb in heartbeats:
        wid = hb.get("worker_id", "unknown")
        result.append({
            **hb,
            "is_stale": wid in stale_set,
        })
    return result


@router.get("/stats")
async def worker_stats(broker: RedisBroker = Depends(get_broker)):
    monitor = HeartbeatMonitor(broker.client, config.HEARTBEAT_TIMEOUT)
    heartbeats = await monitor.get_all_heartbeats()
    stale = await monitor.get_stale_workers()
    total = len(heartbeats)
    dead = len(stale)
    return {
        "total": total,
        "active": total - dead,
        "dead": dead,
    }


@router.get("/{worker_id}")
async def get_worker(worker_id: str, broker: RedisBroker = Depends(get_broker)):
    monitor = HeartbeatMonitor(broker.client, config.HEARTBEAT_TIMEOUT)
    heartbeats = await monitor.get_all_heartbeats()
    for hb in heartbeats:
        if hb.get("worker_id") == worker_id:
            return hb
    return {"worker_id": worker_id, "status": "NOT_FOUND"}
