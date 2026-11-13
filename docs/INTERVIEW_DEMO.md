# CelerLite interview walkthrough

## 30-second introduction

> CelerLite is a Python task queue for running background work outside a web request. FastAPI accepts tasks, Redis coordinates claims and retries, and PostgreSQL stores task history when configured. The challenge was handling a worker that reports success after its claim expires. Each delivery gets its own receipt. I use Lua to check that receipt and commit the result in one Redis operation, so a stale worker cannot overwrite the result from the current delivery.

## Show it in three minutes

1. **Show the workspace.** Open the [live preview](https://celerlite.onrender.com/) and choose **Preview the demo**. The CRM records are synthetic and read-only.
2. **Run a task.** Open **Queue lab**, keep `Add` selected, and submit `20` and `22`. The page sends an allowlisted task through the hosted in-memory broker and embedded worker, then polls its session-scoped result (`42`). This path is real task execution, but jobs and results are ephemeral and do not enter private task history.
3. **Explain the reliability boundary.** The public Queue Lab runs on the hosted in-memory path. It does not exercise Redis receipt fencing. Show the Redis implementation and run the regression below to demonstrate why a stale worker cannot commit after reassignment.

### Start the local task console on Windows

Use a local virtual environment with `requirements.txt` installed. This uses the
embedded worker and a separate SQLite database. Start it in a fresh PowerShell
terminal so the local authentication override applies only to that terminal.

```powershell
$env:CELERLITE_AUTH_REQUIRED = 'false'
$env:CELERLITE_API_HOST = '127.0.0.1'
$env:CELERLITE_API_PORT = '8001'
$env:CELERLITE_REDIS_URL = 'redis://127.0.0.1:6398/0'
$env:CELERLITE_DATABASE_URL = 'sqlite+aiosqlite:///./celerlite_interview.db'
python scripts/run_api.py
```

Open [the local dashboard](http://127.0.0.1:8001/). Port 6398 must be unused to
select the embedded worker. This demo checks task submission, execution, and the
inspector. Use the real Redis test for the distributed failure case.

### Demonstrate reassignment against real Redis

With a local Redis listening on port 6379, use a separate PowerShell terminal:

```powershell
$env:CELERLITE_TEST_REDIS_URL = 'redis://127.0.0.1:6379/15'
python -m pytest -q tests/integration/test_redis_reliability.py -k reassigned_delivery
```

Read the [test](../tests/integration/test_redis_reliability.py) alongside the
[broker implementation](../celerlite/broker/redis_broker.py). Look for the test
named `test_reassigned_delivery_cannot_be_finished_by_stale_worker`.

## Questions to practice

| Question | Answer |
|---|---|
| What is the difference between a task ID and a receipt? | The task ID identifies the work. The receipt identifies one delivery. A redelivery gets a fresh receipt. |
| Why use Lua? | A worker's receipt could expire between separate check and write commands. The Redis script checks ownership and changes state in one operation. |
| Can two workers still execute the same task? | Yes. The old worker can resume after reassignment. Receipts protect the queue and Redis result. An external operation like charging a card needs its own idempotency key. |
| What if dead-letter storage is unavailable? | The worker leaves the task recoverable until persistence succeeds. Redis and PostgreSQL have separate transactions, so a failure between the database write and acknowledgment still needs handling. |
| What does 2,092 messages/sec measure? | A local reserve-and-ack benchmark with 10,000 messages and 10 consumers. It observed 10,000 unique completions and zero missing or duplicate completions. It excludes handler execution and database persistence. |

The [benchmark record](../benchmarks/broker_results_20261112.json) and
[reliability notes](RELIABILITY.md) give the environment and reproduction commands.
