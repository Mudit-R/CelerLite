"""FastAPI application factory."""

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from celerlite.broker.redis_broker import RedisBroker
from celerlite.config import config
from celerlite.observability.logger import get_logger, setup_logging
from celerlite.persistence.database import init_db

logger = get_logger(__name__)

# Shared broker instance for the API process
_broker: RedisBroker = None


def get_broker():
    global _broker
    if _broker is None:
        from celerlite.broker.memory_broker import InMemoryBroker
        _broker = InMemoryBroker(config)
    return _broker


def set_broker(broker: RedisBroker) -> None:
    global _broker
    _broker = broker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global _broker
    setup_logging(config.LOG_LEVEL, config.LOG_FORMAT)
    embedded_task = None
    stop_event = asyncio.Event()

    try:
        redis_broker = RedisBroker(config)
        await redis_broker.connect()
        _broker = redis_broker
        logger.info("redis_connected", url=config.REDIS_URL)
    except Exception as e:
        logger.warning(
            "redis_unavailable_fallback_memory",
            msg="Redis unreachable at localhost:6379. Operating in zero-dependency Standalone Mode with InMemoryBroker & SQLite.",
            error=str(e),
        )
        from celerlite.broker.memory_broker import InMemoryBroker
        from celerlite.worker.embedded import run_embedded_worker

        _broker = InMemoryBroker(config)
        await _broker.connect()
        embedded_task = asyncio.create_task(
            run_embedded_worker(_broker, stop_event=stop_event)
        )

    await init_db()
    logger.info("api_started", host=config.API_HOST, port=config.API_PORT)
    yield
    stop_event.set()
    if embedded_task:
        embedded_task.cancel()
        try:
            await embedded_task
        except (asyncio.CancelledError, Exception):
            pass
    if _broker:
        await _broker.disconnect()
    logger.info("api_stopped")


def create_app() -> FastAPI:
    from celerlite.api.routes import dlq, metrics, tasks, workers
    from fastapi import Depends

    app = FastAPI(
        title="CelerLite",
        description="Distributed Task Queue Engine — Real-Time Monitoring & Control",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers
    app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])
    app.include_router(workers.router, prefix="/api/v1/workers", tags=["Workers"])
    app.include_router(dlq.router, prefix="/api/v1/dlq", tags=["Dead Letter Queue"])
    app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["Metrics"])

    # WebSocket
    from celerlite.api.websocket import router as ws_router
    app.include_router(ws_router)

    # Serve dashboard
    import os
    dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")
    dashboard_dir = os.path.abspath(dashboard_dir)
    if os.path.isdir(dashboard_dir):
        app.mount("/static", StaticFiles(directory=dashboard_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        import os
        index_path = os.path.join(dashboard_dir, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return {"message": "CelerLite API is running", "docs": "/docs"}

    @app.get("/health")
    async def health(broker: RedisBroker = Depends(get_broker)):
        try:
            if broker:
                redis_info = await broker.get_redis_info()
            else:
                redis_info = {"connected": False}
        except Exception:
            redis_info = {"connected": False}
        return {"status": "healthy", "redis": redis_info}

    return app

