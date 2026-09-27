#!/usr/bin/env python3
"""
Throughput Benchmark — Measures sustained tasks/sec across worker counts.

Run with: python benchmarks/throughput_benchmark.py
Requires: Redis running on localhost:6379
"""

import asyncio
import statistics
import time
import uuid
from typing import Any

import redis.asyncio as aioredis

REDIS_URL = "redis://localhost:6379/0"
QUEUE = "celerlite:queue:benchmark:normal"
PROC_QUEUE = "celerlite:processing:benchmark:normal"
RESULT_PREFIX = "celerlite:result:"


async def submit_tasks(client: aioredis.Redis, n: int) -> list[str]:
    """Submit N no-op tasks and return their task IDs."""
    import json
    task_ids = []
    pipe = client.pipeline()
    for _ in range(n):
        tid = str(uuid.uuid4())
        msg = json.dumps({
            "task_id": tid,
            "task_name": "benchmark.noop",
            "args": [], "kwargs": {},
            "queue": "benchmark", "priority": 1,
            "retry_count": 0, "max_retries": 0,
            "timeout": 10, "eta": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "metadata": {}, "revoked": False,
        }).encode()
        pipe.lpush(QUEUE, msg)
        task_ids.append(tid)
    await pipe.execute()
    return task_ids


async def wait_for_results(client: aioredis.Redis, task_ids: list[str], timeout: float = 60.0) -> int:
    """Poll until all tasks have results or timeout. Returns count completed."""
    deadline = time.time() + timeout
    completed = 0
    while time.time() < deadline and completed < len(task_ids):
        pipe = client.pipeline()
        for tid in task_ids:
            pipe.exists(f"{RESULT_PREFIX}{tid}")
        results = await pipe.execute()
        completed = sum(results)
        if completed < len(task_ids):
            await asyncio.sleep(0.1)
    return completed


async def run_benchmark(n_tasks: int, description: str) -> dict:
    client = aioredis.Redis.from_url(REDIS_URL, decode_responses=False)
    try:
        # Flush any leftover data
        await client.delete(QUEUE, PROC_QUEUE)

        print(f"\n  Submitting {n_tasks:,} tasks...")
        submit_start = time.perf_counter()
        task_ids = await submit_tasks(client, n_tasks)
        submit_duration = time.perf_counter() - submit_start

        print(f"  Submitted in {submit_duration:.2f}s. Waiting for completion...")
        wait_start = time.perf_counter()
        completed = await wait_for_results(client, task_ids, timeout=120)
        total_duration = time.perf_counter() - wait_start

        tps = completed / total_duration if total_duration > 0 else 0

        return {
            "description": description,
            "n_tasks": n_tasks,
            "completed": completed,
            "duration_s": round(total_duration, 2),
            "tps": round(tps, 1),
        }
    finally:
        await client.aclose()


async def main():
    print("\n" + "=" * 72)
    print("  CELERLITE THROUGHPUT BENCHMARK")
    print("  NOTE: Ensure workers are running: python scripts/run_worker.py")
    print("=" * 72)

    configs = [
        (1_000, "1,000 tasks"),
        (5_000, "5,000 tasks"),
        (10_000, "10,000 tasks"),
    ]

    results = []
    for n, desc in configs:
        r = await run_benchmark(n, desc)
        results.append(r)
        print(f"  [OK] {desc}: {r['tps']:,.0f} tasks/sec in {r['duration_s']}s ({r['completed']}/{n} completed)")

    print("\n" + "=" * 72)
    print(f"  {'Tasks':>10} | {'Duration':>10} | {'Throughput':>15}")
    print("-" * 72)
    for r in results:
        print(f"  {r['n_tasks']:>10,} | {r['duration_s']:>9.2f}s | {r['tps']:>12,.0f} t/s")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
