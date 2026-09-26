#!/usr/bin/env python3
"""
CelerLite — One-Click Universal Launcher
Runs the API server, real-time WebSocket event streaming, and dashboard.
Auto-detects Redis & PostgreSQL, falling back to embedded mode if external services are not running.
"""

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
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import uvicorn
from celerlite.config import config
from celerlite.observability.logger import setup_logging

if __name__ == "__main__":
    setup_logging(config.LOG_LEVEL, config.LOG_FORMAT)
    banner = f"""
========================================================================
[+] CELERLITE -- Distributed Task Queue & Execution Engine
========================================================================
  * Dashboard UI:        http://localhost:{config.API_PORT}
  * Swagger REST Docs:   http://localhost:{config.API_PORT}/docs
  * WebSocket Stream:    ws://localhost:{config.API_PORT}/api/v1/ws/events
  * Prometheus Metrics:  http://localhost:{config.API_PORT}/api/v1/metrics
========================================================================
[*] Note: If Redis/PostgreSQL are not running locally, CelerLite automatically
    runs in high-performance Standalone Mode with SQLite & embedded worker.
========================================================================
"""
    print(banner)
    uvicorn.run(
        "celerlite.api.app:create_app",
        factory=True,
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
        log_level=config.LOG_LEVEL.lower(),
    )
