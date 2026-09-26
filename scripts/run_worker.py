#!/usr/bin/env python3
"""Start the CelerLite worker pool."""

import os
import signal
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

from celerlite.config import config
from celerlite.observability.logger import get_logger, setup_logging
from celerlite.worker.pool import WorkerPool

logger = get_logger(__name__)


def main():
    setup_logging(config.LOG_LEVEL, config.LOG_FORMAT)
    print("\n" + "=" * 60)
    print("[+] CelerLite Worker Pool")
    print(f"[*] Concurrency: {config.WORKER_CONCURRENCY} worker processes")
    print(f"[*] Redis Broker: {config.REDIS_URL}")
    print("=" * 60 + "\n")

    pool = WorkerPool(config)

    def shutdown(signum, frame):
        logger.info("shutdown_requested", signal=signum)
        pool.stop(timeout=30)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info("starting_worker_pool", concurrency=config.WORKER_CONCURRENCY)
    try:
        pool.start()
    except Exception as e:
        print(f"\n[!] Unable to connect to Redis at {config.REDIS_URL}: {e}")
        print("[*] If you want to run CelerLite without external Redis, run:")
        print("    python run.py")
        print("    (This runs the server with the embedded engine and dashboard)\n")
        sys.exit(1)

    # Keep main thread alive
    import time

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
