#!/usr/bin/env python3
"""Demo script: submit a variety of tasks to show CelerLite features."""

import asyncio
import os
import sys

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from celerlite.config import config
from celerlite.scheduler.priority import Priority


async def main():
    api_url = f"http://localhost:{config.API_PORT}/api/v1/tasks/submit"
    print("\n" + "=" * 60)
    print("[+] CelerLite Demo -- Submitting tasks to API...")
    print(f"[*] Target Endpoint: {api_url}")
    print("=" * 60 + "\n")

    tasks = [
        # Normal tasks
        {"task_name": "celerlite.demo.add", "args": [1, 2], "priority": Priority.NORMAL, "desc": "Add 1+2"},
        {"task_name": "celerlite.demo.add", "args": [10, 20], "priority": Priority.NORMAL, "desc": "Add 10+20"},
        # High priority
        {"task_name": "celerlite.demo.send_email", "args": ["user@example.com", "Welcome!"], "priority": Priority.HIGH, "desc": "High priority email"},
        # Critical
        {"task_name": "celerlite.demo.multiply", "args": [7, 8], "priority": Priority.CRITICAL, "desc": "Critical calculation (7*8)"},
        # Heavy task
        {"task_name": "celerlite.demo.heavy_computation", "args": [5000], "priority": Priority.LOW, "desc": "Heavy computation (5k loop)"},
        # Task that will fail for DLQ demonstration
        {"task_name": "celerlite.demo.failing_task", "priority": Priority.NORMAL, "max_retries": 2, "desc": "Simulated failure (tests DLQ)"},
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Check health first
        try:
            health_resp = await client.get(f"http://localhost:{config.API_PORT}/health")
            if health_resp.status_code != 200:
                print(f"[!] Server returned status {health_resp.status_code}. Is run.py running?")
        except Exception as e:
            print(f"[!] Could not connect to http://localhost:{config.API_PORT}. Please start the server first with: python run.py")
            return

        for t in tasks:
            payload = {
                "task_name": t["task_name"],
                "args": t.get("args", []),
                "kwargs": t.get("kwargs", {}),
                "queue": "default",
                "priority": int(t.get("priority", Priority.NORMAL)),
                "max_retries": t.get("max_retries", 3),
            }
            try:
                resp = await client.post(api_url, json=payload)
                data = resp.json()
                print(f"  [+] [{t['desc']}] task_id={data.get('task_id', '')[:8]}... priority={Priority(int(t.get('priority', Priority.NORMAL))).name}")
            except Exception as e:
                print(f"  [!] Failed to submit {t['desc']}: {e}")

        # Bulk submit
        print("\n[*] Submitting 25 bulk tasks...")
        for i in range(25):
            payload = {
                "task_name": "celerlite.demo.add",
                "args": [i, i * 2],
                "queue": "default",
                "priority": int(Priority.NORMAL),
            }
            await client.post(api_url, json=payload)

    print(f"\n[+] All tasks submitted! Open http://localhost:{config.API_PORT} to watch them process.\n")


if __name__ == "__main__":
    asyncio.run(main())
