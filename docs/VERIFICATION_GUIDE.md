# CelerLite System Verification & Reliability Guide

## Overview

> CelerLite is an asynchronous distributed task engine designed for decoupling background operations from web request lifecycles. FastAPI exposes task ingestion and status streaming, Redis coordinates priority scheduling, lease renewals, and failure retries, and PostgreSQL manages durable task audit history. 

A central engineering challenge in distributed worker fleets is preventing **zombie workers** from committing stale results after a lease expires. CelerLite enforces an atomic fencing receipt mechanism: every delivery lease carries a unique, monotonic receipt token. Redis Lua scripts verify this receipt token and commit results in a single atomic transaction, preventing reassigned or stale workers from overwriting broker state.

---

## Interactive Walkthrough

1. **Access the Console**: Navigate to the [live deployment](https://celerlite.onrender.com/) and select **Preview the demo** to view the live dashboard and queue activity.
2. **Submit a Task**: In the **Queue Lab**, select `Add`, input parameters `[20, 22]`, and submit. The web application dispatches the task through the task pipeline, polling its completed outcome (`42`).
3. **Inspect Task Lifecycle**: Open the Task Inspector to verify execution timestamps, worker identifier, status transitions, and saved outputs.

---

## Local Verification Setup

To inspect task execution, scheduling, and local worker fleet operations:

```powershell
# Set local development parameters
$env:CELERLITE_AUTH_REQUIRED = 'false'
$env:CELERLITE_API_HOST = '127.0.0.1'
$env:CELERLITE_API_PORT = '8001'
$env:CELERLITE_REDIS_URL = 'redis://127.0.0.1:6398/0'
$env:CELERLITE_DATABASE_URL = 'sqlite+aiosqlite:///./celerlite_local.db'

# Launch API and local worker supervisor
python scripts/run_api.py
```

Access the dashboard at [http://127.0.0.1:8001/](http://127.0.0.1:8001/).

---

## Distributed Reassignment & Stale Worker Regression

To verify receipt-based fencing against a live Redis instance (testing worker lease expiration and rejection of stale worker acknowledgments):

```powershell
$env:CELERLITE_TEST_REDIS_URL = 'redis://127.0.0.1:6379/15'
python -m pytest -q tests/integration/test_redis_reliability.py -k reassigned_delivery
```

This regression validates `test_reassigned_delivery_cannot_be_finished_by_stale_worker` in `tests/integration/test_redis_reliability.py` against `celerlite/broker/redis_broker.py`.

---

## Technical Invariants & FAQ

| Architecture Invariant | System Design Implementation |
|:---|:---|
| **What distinguishes a Task ID from a Delivery Receipt?** | The `task_id` uniquely identifies the immutable unit of work across its lifecycle. The `receipt` is a transient 32-byte UUID token identifying a single delivery lease. Reassigned or retried deliveries receive a new receipt. |
| **Why are Lua scripts required for state transitions?** | A worker's lease could expire during the network round-trip between separate check and write commands. Redis Lua scripts execute atomically on Redis's single thread, verifying receipt ownership and committing state without race conditions. |
| **Can two workers execute the same task concurrently?** | Yes, under network partitions or heavy GC stalls. If Worker A's lease expires, Worker B assumes the task. When Worker A unpauses, both execute concurrently. Receipt fencing guarantees the broker and Redis result store only accept the legitimate lease. Handlers with external side-effects (e.g., credit card charges) must maintain application-level idempotency keys. |
| **How does CelerLite handle dead-letter persistence failure?** | Workers employ a recoverable-before-ack pattern: tasks remain unacknowledged in Redis until the dead-letter database write succeeds. If the database is unreachable, the task remains safely recoverable in Redis. |
| **What workload does the 2,091.5 msg/sec benchmark represent?** | A local reserve-and-ack benchmark with 10,000 messages across 10 consumer processes, measuring zero missing or duplicate completions under strict priority and receipt verification. |
