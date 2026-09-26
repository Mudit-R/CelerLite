#!/usr/bin/env python3
"""Demo script: submit a variety of tasks to show CelerLite features."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from celerlite.broker.redis_broker import RedisBroker
from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.config import config
from celerlite.scheduler.priority import Priority
import uuid


async def main():
    broker = RedisBroker(config)
    await broker.connect()
    print("\n🚀 CelerLite Demo — Submitting tasks...\n")

    tasks = [
        # Normal tasks
        {"task_name": "celerlite.demo.add", "args": [1, 2], "priority": Priority.NORMAL, "desc": "Add 1+2"},
        {"task_name": "celerlite.demo.add", "args": [10, 20], "priority": Priority.NORMAL, "desc": "Add 10+20"},
        # High priority
        {"task_name": "celerlite.demo.greet", "kwargs": {"name": "Mudit"}, "priority": Priority.HIGH, "desc": "High priority greet"},
        # Critical
        {"task_name": "celerlite.demo.system_check", "priority": Priority.CRITICAL, "desc": "Critical system check"},
        # Slow task (tests timeout visibility)
        {"task_name": "celerlite.demo.slow_task", "args": [3], "priority": Priority.LOW, "desc": "Slow task (3s)"},
        # Task that will fail → retry → DLQ demo
        {"task_name": "celerlite.demo.always_fail", "priority": Priority.NORMAL, "max_retries": 2, "desc": "Always fails (→ DLQ)"},
    ]

    for t in tasks:
        msg = TaskMessage(
            task_id=str(uuid.uuid4()),
            task_name=t["task_name"],
            args=t.get("args", []),
            kwargs=t.get("kwargs", {}),
            queue="default",
            priority=int(t.get("priority", Priority.NORMAL)),
            max_retries=t.get("max_retries", 3),
        )
        raw = Serializer.serialize(msg)
        await broker.enqueue("default", raw, priority=int(t.get("priority", Priority.NORMAL)))
        print(f"  ✓ [{t['desc']}] task_id={msg.task_id[:8]}… priority={Priority(int(t.get('priority', Priority.NORMAL))).name}")

    # Bulk submit
    print(f"\n📦 Submitting 100 bulk tasks...")
    for i in range(100):
        msg = TaskMessage(
            task_id=str(uuid.uuid4()),
            task_name="celerlite.demo.add",
            args=[i, i * 2],
            queue="default",
            priority=int(Priority.NORMAL),
        )
        raw = Serializer.serialize(msg)
        await broker.enqueue("default", raw)

    print(f"\n✅ All tasks submitted! Open http://localhost:{config.API_PORT} to watch them process.\n")
    await broker.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
