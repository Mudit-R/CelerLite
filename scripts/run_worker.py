#!/usr/bin/env python3
"""Start the CelerLite worker pool."""

import signal
import sys

from celerlite.config import config
from celerlite.observability.logger import setup_logging, get_logger
from celerlite.worker.pool import WorkerPool

logger = get_logger(__name__)


def main():
    setup_logging(config.LOG_LEVEL, config.LOG_FORMAT)
    pool = WorkerPool(config)

    def shutdown(signum, frame):
        logger.info("shutdown_requested", signal=signum)
        pool.stop(timeout=30)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info("starting_worker_pool", concurrency=config.WORKER_CONCURRENCY)
    pool.start()

    # Keep main thread alive
    import time
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
