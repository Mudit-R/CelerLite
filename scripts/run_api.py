#!/usr/bin/env python3
"""Start the CelerLite API server & dashboard."""

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

import uvicorn
from celerlite.config import config
from celerlite.observability.logger import setup_logging

if __name__ == "__main__":
    setup_logging(config.LOG_LEVEL, config.LOG_FORMAT)
    print("\n" + "=" * 60)
    print("[+] CelerLite Distributed Task Engine")
    print(f"[*] Dashboard & API: http://localhost:{config.API_PORT}")
    print(f"[*] Swagger Docs:    http://localhost:{config.API_PORT}/docs")
    print("=" * 60 + "\n")
    uvicorn.run(
        "celerlite.api.app:create_app",
        factory=True,
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
        log_level=config.LOG_LEVEL.lower(),
    )
