"""FastAPI application factory."""

import asyncio
import json
import os
import sys
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

    is_serverless = bool(
        os.environ.get("VERCEL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("VERCEL_ENV")
    )

    if not is_serverless:
        embedded_mode = False
        try:
            if config.DEMO_READ_ONLY and not config.AUTH_REQUIRED:
                raise RuntimeError('Public demo uses the isolated in-memory broker')
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
            embedded_mode = True

        # Initialize and seed before starting workers or serving concurrent requests.
        await init_db()
        from celerlite.persistence.database import get_session
        from celerlite.persistence.crm_repository import CRMRepository
        async with get_session() as session:
            await CRMRepository(session).seed_demo_data_if_empty()
        if embedded_mode:
            embedded_task = asyncio.create_task(
                run_embedded_worker(_broker, stop_event=stop_event)
            )
        logger.info("api_started", host=config.API_HOST, port=config.API_PORT)
    else:
        from celerlite.broker.memory_broker import InMemoryBroker

        _broker = InMemoryBroker(config)
        await _broker.connect()
        await init_db()

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


def create_app(serverless: bool = False) -> FastAPI:
    from celerlite.api.routes import crm, dlq, metrics, tasks, workers
    from celerlite.api.auth import router as auth_router, verified_user, valid_origin, COOKIE
    from fastapi import Depends
    from starlette.responses import JSONResponse

    is_serverless = (
        serverless
        or bool(
            os.environ.get("VERCEL")
            or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
            or os.environ.get("VERCEL_ENV")
        )
    )
    app_lifespan = None if is_serverless else lifespan

    app = FastAPI(
        title="CelerLite CRM & Task Engine",
        description="Enterprise Distributed CRM Platform & High-Throughput Task Queue",
        version="1.0.0",
        lifespan=app_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.middleware('http')
    async def protect_workspace(request, call_next):
        if (config.DEMO_READ_ONLY and request.url.path.startswith('/api/v1/')
                and request.method not in ('GET', 'HEAD', 'OPTIONS')):
            return JSONResponse({'detail': 'This public demo is read-only'}, status_code=403,
                                headers={'Cache-Control': 'no-store'})
        if config.AUTH_REQUIRED and request.url.path.startswith('/api/v1/'):
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and not valid_origin(request.headers.get('origin')):
                return JSONResponse({'detail': 'Invalid request origin'}, status_code=403)
            if not await verified_user(request.cookies.get(COOKIE)):
                return JSONResponse({'detail': 'Sign in required'}, status_code=401,
                                    headers={'Cache-Control': 'no-store'})
        result = await call_next(request)
        if request.url.path.startswith('/api/v1/'):
            result.headers['Cache-Control'] = 'no-store'
        return result

    app.include_router(auth_router)

    # REST routers
    app.include_router(crm.router, prefix="/api/v1/crm", tags=["CRM"])
    app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])
    app.include_router(workers.router, prefix="/api/v1/workers", tags=["Workers"])
    app.include_router(dlq.router, prefix="/api/v1/dlq", tags=["Dead Letter Queue"])
    app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["Metrics"])

    # WebSocket
    from celerlite.api.websocket import router as ws_router
    app.include_router(ws_router)

    # Serve dashboard & static assets (robust cross-platform and Vercel serverless resolution)
    from fastapi.responses import HTMLResponse, Response

    possible_dirs = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "api", "dashboard")),
        os.path.abspath(os.path.join(os.getcwd(), "api", "dashboard")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")),
        os.path.abspath(os.path.join(os.getcwd(), "dashboard")),
        "/var/task/api/dashboard",
        "/var/task/dashboard",
    ]

    def get_dashboard_path(filename: str = "index.html") -> str:
        for d in possible_dirs:
            root = os.path.realpath(d)
            p = os.path.realpath(os.path.join(root, filename))
            try:
                if os.path.commonpath([root, p]) == root and os.path.isfile(p):
                    return p
            except ValueError:
                continue
        return ""

    @app.get("/static/{file_path:path}", include_in_schema=False)
    @app.get("/api/static/{file_path:path}", include_in_schema=False)
    async def serve_static_file(file_path: str):
        full_path = get_dashboard_path(file_path)
        if full_path and os.path.isfile(full_path):
            mime_type = "text/plain"
            if file_path.endswith(".css"):
                mime_type = "text/css"
            elif file_path.endswith(".js"):
                mime_type = "application/javascript"
            elif file_path.endswith(".html"):
                mime_type = "text/html"
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                return Response(content=f.read(), media_type=mime_type)
        return Response(content="/* asset not found */", media_type="text/plain", status_code=404)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/api", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/api/index.py", response_class=HTMLResponse, include_in_schema=False)
    async def serve_dashboard():
        index_file = get_dashboard_path("index.html")
        if index_file and os.path.isfile(index_file):
            with open(index_file, "r", encoding="utf-8", errors="ignore") as f:
                return HTMLResponse(content=f.read(), headers={'Cache-Control': 'no-store'})
        return HTMLResponse(content="<h1>CelerLite Console</h1><p>API Server is ONLINE. View docs at <a href='/docs'>/docs</a>.</p>")

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

