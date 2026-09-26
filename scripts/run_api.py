#!/usr/bin/env python3
"""Start the CelerLite API server."""

import uvicorn
from celerlite.api.app import create_app
from celerlite.config import config
from celerlite.observability.logger import setup_logging

if __name__ == "__main__":
    setup_logging(config.LOG_LEVEL, config.LOG_FORMAT)
    app = create_app()
    uvicorn.run(
        "celerlite.api.app:create_app",
        factory=True,
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
        log_level=config.LOG_LEVEL.lower(),
    )
