# CelerLite interview walkthrough

## 30-second introduction

> CelerLite is a Python task queue for running background work outside a web request. FastAPI accepts tasks, Redis coordinates claims and retries, and PostgreSQL stores task history when configured. The challenge was handling a worker that reports success after its claim expires. Each delivery gets its own receipt. I use Lua to check that receipt and commit the result in one Redis operation, so a stale worker cannot overwrite the result from the current delivery.

## Show it in three minutes

1. **Show the workspace.** Open the [live preview](https://celerlite.onrender.com/) and choose **Preview the demo**. It shows a synthetic CRM workspace. Use a local instance or an approved workspace account to demonstrate task submission.
2. **Run a task.** In the local task console, select **Run Custom Task**. Enter `celerlite.demo.add`, queue `default`, positional arguments `[20, 22]`, and keyword arguments `{}`. Open the task inspector and confirm status `SUCCESS` and result `42`. Point out the task ID and saved execution details.
3. **Show the failure case.** Run the Redis regression below. Walk through Worker A's claim, expiration, Worker B's new receipt, and the rejected completion from A. B then records the result with the current receipt.

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
