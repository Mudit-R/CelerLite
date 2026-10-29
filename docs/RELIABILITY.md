# Broker reliability and measured validation

## Changes, 2026-10-30

- Lua reservation checks four priority queues in one atomic operation and records
  the reservation timestamp using Redis server time in the same operation.
- Idle consumers poll all priorities at up to 50ms intervals instead of blocking
  exclusively on the critical queue. This is a polling interval, not a latency SLA.
- Acknowledgement, rejection/requeue and stale recovery update processing lists,
  timestamps and pending lists atomically. Rejection preserves original priority.
- A failed task's retry payload replaces its reservation in one Redis operation;
  deferred tasks use atomic requeue. Dead-letter persistence must succeed before
  acknowledgement, so a failed database write leaves the task recoverable.
- Cancellation remains supported; positive timeouts bound waiting and zero waits
  indefinitely. Unit and real Redis integration suites are wired into CI.

## Evidence

Local validation: **66 tests passed**, including **12 real Redis integration tests**.
The integration suite tests all four priorities, FIFO, ten concurrent consumers,
concurrent recovery, priority-preserving rejection, timeouts/cancellation, and
recovery after an actual consumer subprocess is killed with unacknowledged work.

The checked-in `benchmarks/broker_results_20261030.json` records a **10,000-message**
reserve-and-ack workload using ten async consumers: **10,000 unique completions,
zero missing messages, zero duplicates**, 3.248 seconds (3,079.1 messages/sec).
Environment: Windows, Python 3.11.9, Redis 7.4.12 in local Docker. This measures
broker operations after enqueueing, not execution of user tasks, HTTP latency,
database persistence, or performance under network partitions. Results vary by host.

Reproduce:

```
CELERLITE_TEST_REDIS_URL=redis://localhost:6379/15 python -m pytest -q
python -m benchmarks.broker_reliability --redis-url redis://localhost:6379/15 --tasks 10000 --output broker_results.json
```

On PowerShell set the environment variable with `$env:CELERLITE_TEST_REDIS_URL`.
Tests and benchmark use UUID-named queues, never FLUSHDB.

## Boundaries

This remains an **at-least-once** list-based broker. Handlers must make business
side effects idempotent. Visibility timeouts must exceed task duration; a live
slow worker can otherwise overlap redelivery. The current API does not expose
delivery receipts/fencing tokens, and these changes do not establish exactly-once
effects or safe late acknowledgements after lease expiry. A future receipt/lease
API would address those cases. The Lua scripts target standalone Redis, not Redis
Cluster. They process each priority's in-flight list atomically; very large lists
should use bounded recovery batches in a future revision.
Redis and the dead-letter database do not share a transaction: a crash after a
successful dead-letter write but before acknowledgement may cause a repeated write;
dead-letter persistence should be made idempotent in future work.

## Task inspector validation

The follow-up API suite includes invalid payload rejection before enqueueing and
persisted task detail checks. Full local validation after this change: 78 tests
passed, including 12 real Redis integration tests. Browser checks used an isolated
SQLite database and the embedded worker: `[20, 22]` returned `42`; missing required
arguments surfaced as a failed execution; malformed argument types stayed in the
form. The inspector displays stored database records, not a distributed trace.
