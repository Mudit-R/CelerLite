# CelerLite — Distributed Background Task Queue & Operations Engine

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Render-46E3B7?logo=render&logoColor=white)](https://celerlite.onrender.com/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Redis](https://img.shields.io/badge/Redis-7.0+-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

> **Live Deployment**: [https://celerlite.onrender.com/](https://celerlite.onrender.com/)  
> **Swagger API Docs**: [https://celerlite.onrender.com/docs](https://celerlite.onrender.com/docs)  
> **CelerLite** is a high-throughput, distributed background task execution engine built with Python, FastAPI, and Redis. It provides strict multi-queue priority scheduling, receipt-fenced atomic state transitions, exponential backoff retries with full jitter, dead-letter queue management, and real-time WebSocket telemetry.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Core Engineering Highlights](#core-engineering-highlights)
- [Reliability & Delivery Guarantees](#reliability--delivery-guarantees)
- [Performance & Benchmarks](#performance--benchmarks)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
  - [Option A: Full Stack with Docker Compose (Recommended)](#option-a-full-stack-with-docker-compose-recommended)
  - [Option B: Local Standalone Development](#option-b-local-standalone-development)
- [Python SDK Usage](#python-sdk-usage)
- [API & WebSocket Reference](#api--websocket-reference)
- [Testing & Quality Assurance](#testing--quality-assurance)
- [License](#license)

---

## System Architecture

CelerLite decouples producers and consumers using Redis for queue scheduling and SQLAlchemy for task and CRM records. PostgreSQL is used in production; local development can seamlessly fall back to SQLite.

```
                        ┌────────────────────────────────────────────────┐
                        │             Producer / Client SDK              │
                        │      @task | .delay() | .apply_async()         │
                        └───────────────────────┬────────────────────────┘
                                                │
                                    (1) Enqueue task payload
                                                v
  ┌────────────────────────────────────────────────────────────────────────────────────────┐
  │                                   Redis Broker Layer                                   │
  │  ┌───────────────────────┬────────────────────────┬─────────────────────────────────┐  │
  │  │  Priority Queues      │  Processing & DLQ      │  Pub/Sub Event Bus              │  │
  │  │  • queue:critical     │  • celerlite:proc:*    │  • celerlite:events:tasks       │  │
  │  │  • queue:high         │  • celerlite:dlq:*     │  • celerlite:events:workers     │  │
  │  │  • queue:normal       │  • celerlite:results:* │                                 │  │
  │  │  • queue:low          │  • celerlite:heartbeat │                                 │  │
  │  └───────────────────────┴────────────────────────┴─────────────────────────────────┘  │
  └───────────────────^───────────────────────────┬───────────────────────────────^────────┘
                      │                           │                               │
        (2) Strict Priority Dequeue   (3) Push Heartbeats & Events    (4) Stream Events
                      │                           │                               │
                      v                           v                               v
  ┌─────────────────────────────────┐ ┌───────────────────────────┐ ┌──────────────────────────┐
  │     Distributed Worker Pool     │ │   PostgreSQL Persistence  │ │   FastAPI Gateway Server │
  │ ┌─────────────────────────────┐ │ │ ┌───────────────────────┐ │ │  • REST API (/api/v1)    │
  │ │ Worker Pool Manager         │ │ │ │ Tasks Audit Log       │ │ │  • WebSocket Stream      │
  │ │  • Dynamic Forking & Reap   │ │ │ │ Workers Fleet Table   │ │ │  • Prometheus Exporter   │
  │ │  • Heartbeat Supervisor     │ │ │ │ Dead Letter Queue     │ │ │  • Operations Dashboard  │
  │ ├─────────────────────────────┤ │ │ └───────────────────────┘ │ └─────────────┬────────────┘
  │ │ Worker Process [1..N]       │ │ └───────────────────────────┘               │
  │ │  • Token-Bucket Limiter     │ │                                             │ WebSockets
  │ │  • Late Ack (TASK_ACK_LATE) │ │                                             v
  │ │  • Timeout Isolation (SIG)  │ │                              ┌───────────────────────────┐
  │ └─────────────────────────────┘ │                              │  Operations Console UI    │
  └─────────────────────────────────┘                              │  Live KPIs, Donut, Fleet  │
                                                                   └───────────────────────────┘
```

---

## Core Engineering Highlights

### 1. Strict Priority Scheduling (Multi-Queue Ordering)
Tasks are enqueued into separate Redis data structures indexed by priority (`CRITICAL=3`, `HIGH=2`, `NORMAL=1`, `LOW=0`). Redis atomically reserves work in priority order within each application queue. Workers poll configured application queues round-robin so a busy default queue does not monopolize the worker.

### 2. At-Least-Once Delivery with Late Acknowledgment (`TASK_ACK_LATE`)
To make work resilient against worker failures:
- Tasks are popped from the ready queue into a dedicated unacknowledged processing registry.
- A task is **only acknowledged and cleared from Redis after successful completion**.
- If a worker crashes with a reserved task, recovery re-enqueues it after the lease reservation expires. Delivery is at-least-once, so task handlers must make external side effects idempotent.
- A fresh delivery receipt identifies each claim. If a task is reassigned after a timeout, Redis rejects an expired worker's acknowledgment. The receipt check, result publication, and acknowledgment execute atomically inside a single Lua script.

### 3. Exponential Backoff with Full Jitter & Dead Letter Queue (DLQ)
Transient failures are retried using truncated exponential backoff with full jitter to avoid the "thundering herd" problem:
$$\text{delay} = \min(\text{backoff\_max},\ \text{backoff\_base}^{\text{retry}} \pm \text{jitter})$$
- Non-recoverable errors marked with `FatalError` bypass retries immediately.
- Tasks exceeding `max_retries` are routed to the **Dead Letter Queue (DLQ)** along with complete contextual metadata, full exception tracebacks, and original execution parameters.
- Operators can inspect failed tasks and replay entries from the dead-letter queue through the REST API or UI.

### 4. Distributed Sliding-Window Token Bucket Rate Limiting
Task types can be rate-limited cluster-wide (e.g. `rate_limit="60/m"` for external APIs). The limiter uses Redis Sorted Sets (`ZREMRANGEBYSCORE`, `ZCARD`, `ZADD`) to enforce a shared sliding window across all concurrent worker processes.

### 5. Task Serialization
Supports both JSON and **MessagePack (`msgpack`)** serialization for efficient network transfer and minimal serialization overhead.

### 6. Workspace UI & Live Telemetry
A native HTML/CSS/JS operations console served directly by FastAPI:
- WebSocket updates driven by Redis Pub/Sub events.
- Live Chart.js throughput graphs & task status donut charts.
- Worker fleet status table with heartbeat health indicators.
- Interactive DLQ explorer with instant replay and task deletion.
- Task submission sandbox for interactive operational testing.

---

## Reliability & Delivery Guarantees

For an in-depth review of broker delivery boundaries, receipt fencing mechanics, and recovery under crash simulations, see:
- [System Verification & Reliability Guide](docs/VERIFICATION_GUIDE.md)
- [Measured Validation & Reliability Boundaries](docs/RELIABILITY.md)
- [Authentication & Security Architecture](docs/AUTHENTICATION.md)

---

## Performance & Benchmarks

In local load testing across **10,000 messages** using 10 concurrent async consumers, the receipt-aware Redis broker achieved:
- **Throughput**: **2,091.5 messages/sec**
- **Consistency**: **10,000 unique completions** with **zero missing or duplicate tasks**
- Detailed reproduction steps, test environments, and raw data are documented in [docs/RELIABILITY.md](docs/RELIABILITY.md).

---

## Project Structure

```
CelerLite/
├── celerlite/                  # Core package
│   ├── api/                    # FastAPI application & endpoints
│   │   ├── routes/             # Tasks, Workers, DLQ, Metrics routes
│   │   ├── app.py              # Application factory & lifespan
│   │   └── websocket.py        # Real-time event streaming via Redis Pub/Sub
│   ├── broker/                 # Queue abstraction & Redis driver
│   │   ├── base.py             # Abstract broker interface
│   │   ├── redis_broker.py     # Redis lists and Lua-based delivery transitions
│   │   └── serializer.py       # JSON & MsgPack serialization layer
│   ├── observability/          # Logging & metrics
│   │   ├── logger.py           # Structured JSON logger
│   │   └── metrics.py          # Prometheus-compatible latency & throughput trackers
│   ├── persistence/            # SQLAlchemy persistence & audit storage
│   │   ├── database.py         # Async SQLAlchemy 2.0 engine & session maker
│   │   ├── models.py           # TaskModel, WorkerModel, DLQEntry
│   │   └── repository.py       # Asynchronous CRUD repositories
│   ├── scheduler/              # Scheduling, throttling & fault-tolerance
│   │   ├── priority.py         # Multi-level priority queue logic
│   │   ├── rate_limiter.py     # Distributed sliding-window token bucket
│   │   └── retry_policy.py     # Exponential backoff + jitter & DLQ routing
│   ├── sdk/                    # Client SDK & task decorators
│   │   └── decorators.py       # @task decorator, AsyncResult handle
│   ├── worker/                 # Worker pool & execution runtime
│   │   ├── heartbeat.py        # Worker liveness publisher & monitor
│   │   ├── pool.py             # Multi-process pool manager & crash supervisor
│   │   └── worker.py           # Worker loop, execution & acknowledgment
│   └── config.py               # Pydantic Settings configuration
├── dashboard/                  # Operations UI (HTML5, CSS3, JS)
│   ├── index.html              # Dashboard layout & KPI cards
│   ├── styles.css              # Responsive workspace design system
│   └── app.js                  # WebSocket stream & Chart.js dynamic updates
├── docker/                     # Containerization
│   └── Dockerfile              # Multi-stage optimized Python container
├── migrations/                 # Alembic database migrations
│   ├── versions/               # Schema revisions (001_initial_schema.py)
│   ├── env.py                  # Async Alembic execution environment
│   └── script.py.mako          # Migration template
├── scripts/                    # CLI entry points
│   ├── run_api.py              # Start FastAPI server
│   ├── run_worker.py           # Start Worker Pool
│   └── submit_demo_tasks.py    # Demo workload generator
├── tests/                      # Unit, integration, and reliability tests
│   ├── unit/                   # Unit tests (priority, rate limiter, broker, api)
│   ├── chaos/                  # Worker crash & recovery simulation tests
│   └── conftest.py             # Shared fixtures & test database
├── docker-compose.yml          # Full-stack composition (Redis, Postgres, API, Workers)
├── pyproject.toml              # Build & test tooling configuration
└── requirements.txt            # Production & dev dependencies
```

---

## Quick Start

### Option A: Full Stack with Docker Compose (Recommended)

Starts Redis 7, PostgreSQL 15, the FastAPI Gateway, 2 worker containers (8 processes total), and the Real-time Dashboard:

```bash
docker-compose up --build
```

Access the services:
- **Operations Dashboard**: [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Prometheus Metrics**: [http://localhost:8000/api/v1/metrics](http://localhost:8000/api/v1/metrics)

---

### Option B: Local Standalone Development

#### 1. Prerequisites
- Python 3.11+
- Redis running on `localhost:6379`
- PostgreSQL (optional, falls back to SQLite for local development)

#### 2. Virtual Environment Setup
```bash
# Clone the repository
git clone https://github.com/Mudit-R/CelerLite.git
cd CelerLite

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### 3. Run the Services
Open separate terminals:

```bash
# Terminal 1: Run the API Server & Dashboard
python scripts/run_api.py

# Terminal 2: Run the Worker Pool (4 processes)
python scripts/run_worker.py

# Terminal 3: Submit Workload
python scripts/submit_demo_tasks.py
```

---

## Python SDK Usage

### 1. Defining Tasks

```python
from celerlite.sdk.decorators import task
from celerlite.scheduler.priority import Priority
from celerlite.scheduler.retry_policy import FatalError

@task(queue="default", max_retries=3, timeout=30)
def process_data(records: list) -> dict:
    return {"processed": len(records), "status": "ok"}

@task(queue="payments", max_retries=5, rate_limit="100/m")
def charge_customer(customer_id: str, amount_cents: int) -> str:
    if amount_cents <= 0:
        raise FatalError("Invalid transaction amount; routing directly to DLQ")
    # Execute payment logic...
    return f"txn_{customer_id}"
```

### 2. Submitting Tasks & Checking Results

```python
# Asynchronous dispatch (fire-and-forget)
async_res = process_data.delay([1, 2, 3, 4, 5])
print(f"Task submitted with ID: {async_res.task_id}")

# Submit with strict priority
vip_task = charge_customer.apply_async(
    args=["cust_9981", 4999],
    priority=Priority.CRITICAL,  # Handled before NORMAL/LOW tasks
    queue="payments"
)

# Blocking retrieval with timeout
result = async_res.get(timeout=10.0)
print(f"Result: {result}")

# Revocation
vip_task.revoke()
```

---

## API & WebSocket Reference

### REST Endpoints

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/api/v1/tasks/submit` | Enqueue a task with priority, args, and timeout |
| `GET` | `/api/v1/tasks/{task_id}` | Retrieve task state, error messages, and timing |
| `GET` | `/api/v1/tasks/{task_id}/result`| Fast-path retrieval of completed result from Redis |
| `POST` | `/api/v1/tasks/{task_id}/revoke`| Mark a task as revoked so workers discard it |
| `GET` | `/api/v1/tasks/stats` | Aggregated counts by status and real-time throughput |
| `GET` | `/api/v1/workers` | List all active/dead workers with heartbeats & PIDs |
| `GET` | `/api/v1/dlq` | List dead-lettered tasks with full tracebacks |
| `POST` | `/api/v1/dlq/{entry_id}/replay` | Re-queue a failed task with reset retry counter |
| `POST` | `/api/v1/dlq/replay-all` | Bulk-replay all dead-lettered tasks |
| `GET` | `/api/v1/metrics` | Prometheus-compatible telemetry snapshot |
| `GET` | `/health` | Broker and database connectivity health check |

### WebSocket Endpoint

```
ws://localhost:8000/api/v1/ws/events
```
Emits real-time JSON frames whenever tasks are submitted, started, completed, failed, retried, or dead-lettered:

```json
{
  "event": "task_completed",
  "task_id": "e6a2b0fd-4f11-48e0-a7d1-9ce4ad2103f5",
  "task_name": "celerlite.demo.add",
  "worker_id": "worker-f481ac90",
  "duration_ms": 1.45,
  "queue": "default"
}
```

---

## Testing & Quality Assurance

The test suite covers unit logic, concurrency boundaries, fault tolerance, and chaos failure scenarios:

```bash
# Run the complete test suite
pytest -v

# Run with test coverage report
pytest --cov=celerlite --cov-report=term-missing
```

### Test Coverage Highlights:
- **Unit Tests**:
  - `test_serializer.py`: MsgPack & JSON serialization round-trips, validation, and payload integrity.
  - `test_priority.py`: Strict priority ordering, key generation, and queue ordering.
  - `test_retry_policy.py`: Exponential backoff calculation, jitter randomization, and FatalError bypassing.
  - `test_rate_limiter.py`: Sliding window sorted-set rate limiting and token bucket throttling.
  - `test_heartbeat.py`: Heartbeat publishing, Redis TTL verification, and stale worker detection.
  - `test_repository.py`: Async SQLAlchemy CRUD, state transitions, and DLQ operations.
  - `test_api.py`: FastAPI endpoints, dependency overrides, and HTTP status codes.
- **Chaos & Fault Tolerance Tests**:
  - `test_worker_crash.py`: Simulates abrupt worker process termination (SIGKILL/OOM) and verifies that the supervisor automatically replaces dead workers.
  - `test_redis_reliability.py`: Tests real Redis concurrent worker reassignments, lease expirations, and receipt-based rejection of stale acknowledgments.

---

## Task Inspection & Sandbox

In the **CelerLite Task Queue & Workers** dashboard, choose **Run Custom Task** to execute tasks directly against the engine with JSON parameters (e.g. `celerlite.demo.add` on `default` with `[20, 22]`). The task inspector displays real-time execution duration, worker IDs, timestamps, and return values.

![Task inspector](docs/task-inspector.jpg)

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
