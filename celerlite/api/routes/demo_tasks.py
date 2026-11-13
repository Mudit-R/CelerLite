"""Small, isolated task surface for the public recruiter preview.

Only deterministic arithmetic is accepted. Jobs live in this API process and
are intentionally separate from task history and private CRM persistence.
"""

import hashlib
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from celerlite.api.app import get_broker
from celerlite.api.auth import DEMO_COOKIE, demo_available, valid_demo_session, valid_origin
from celerlite.broker.memory_broker import InMemoryBroker
from celerlite.broker.serializer import Serializer, TaskMessage

router = APIRouter()
_jobs: dict[str, dict] = {}
_attempts: dict[str, deque[float]] = defaultdict(deque)
_job_ttl = 600
_window = 60
_limit = 6
_max_jobs = 1000


class DemoTaskRequest(BaseModel):
    operation: Literal["add", "multiply"]
    left: int = Field(ge=-10_000, le=10_000)
    right: int = Field(ge=-10_000, le=10_000)


def _session_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune(now: float) -> None:
    for task_id, job in list(_jobs.items()):
        if now - job["created_monotonic"] > _job_ttl:
            _jobs.pop(task_id, None)
    for key, attempts in list(_attempts.items()):
        while attempts and attempts[0] <= now - _window:
            attempts.popleft()
        if not attempts:
            _attempts.pop(key, None)


def _require_demo(request: Request) -> tuple[str, str]:
    token = request.cookies.get(DEMO_COOKIE, "")
    if not demo_available() or not valid_demo_session(token):
        raise HTTPException(401, "Start a fresh demo session to use the queue lab")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not valid_origin(request.headers.get("origin")):
        raise HTTPException(403, "Invalid request origin")
    return token, _session_key(token)


def is_public_demo_task(task_id: str) -> bool:
    """Identify a job created by the guest route, without trusting message metadata."""
    _prune(time.monotonic())
    return task_id in _jobs


@router.get("/capabilities")
async def capabilities(request: Request):
    _require_demo(request)
    from celerlite.api import app as app_module

    available = bool(app_module._embedded_worker_active and isinstance(get_broker(), InMemoryBroker))
    return {
        "available": available,
        "mode": "in-memory embedded worker" if available else "unavailable",
        "retention_seconds": _job_ttl,
        "message": (
            "This runs an allowlisted task through the app's real in-process broker and worker. "
            "Queue state and results are ephemeral and reset when the service restarts."
            if available
            else "The hosted demo worker is not available right now."
        ),
    }


@router.post("")
async def submit_demo_task(body: DemoTaskRequest, request: Request, broker=Depends(get_broker)):
    token, session_key = _require_demo(request)
    from celerlite.api import app as app_module

    if not app_module._embedded_worker_active or not isinstance(broker, InMemoryBroker):
        raise HTTPException(503, "The hosted demo worker is not available right now")

    now = time.monotonic()
    _prune(now)
    if len(_jobs) >= _max_jobs:
        oldest_id = min(_jobs, key=lambda key: _jobs[key]["created_monotonic"])
        _jobs.pop(oldest_id, None)
    attempts = _attempts[session_key]
    while attempts and attempts[0] <= now - _window:
        attempts.popleft()
    if len(attempts) >= _limit:
        raise HTTPException(429, "Queue lab limit reached. Try again in a minute.")
    attempts.append(now)

    task_id = str(uuid.uuid4())
    task_name = f"celerlite.demo.{body.operation}"
    message = TaskMessage(
        task_id=task_id,
        task_name=task_name,
        args=[body.left, body.right],
        queue="default",
        priority=0,
        max_retries=0,
        timeout=5,
        metadata={"public_demo": True},
    )
    _jobs[task_id] = {
        "session_key": session_key,
        "task_name": task_name,
        "args": [body.left, body.right],
        "status": "PENDING",
        "created_monotonic": now,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await broker.enqueue(message.queue, Serializer.serialize(message), priority=message.priority)
    except Exception as exc:
        _jobs.pop(task_id, None)
        raise HTTPException(503, "Could not enqueue the demo task") from exc
    return {"task_id": task_id, "status": "PENDING", "task_name": task_name}


@router.get("/{task_id}")
async def get_demo_task(task_id: str, request: Request, broker=Depends(get_broker)):
    _, session_key = _require_demo(request)
    _prune(time.monotonic())
    job = _jobs.get(task_id)
    if not job or job["session_key"] != session_key:
        raise HTTPException(404, "Demo task not found")

    payload = {
        "task_id": task_id,
        "task_name": job["task_name"],
        "args": job["args"],
        "status": job["status"],
        "created_at": job["created_at"],
    }
    raw_result = await broker.get_result(task_id)
    if raw_result:
        result = Serializer.deserialize_result(raw_result)
        payload.update({"status": result.status, "result": result.result,
                        "error": result.error, "duration_ms": result.duration_ms,
                        "completed_at": result.completed_at})
    return payload
