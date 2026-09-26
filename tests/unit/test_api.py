"""Unit tests for FastAPI REST API endpoints."""

import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from celerlite.api.app import create_app, get_broker
from celerlite.persistence.models import Base
import celerlite.persistence.database as db_mod
import celerlite.api.routes.tasks as tasks_route_mod
import celerlite.api.routes.dlq as dlq_route_mod
import celerlite.api.routes.workers as workers_route_mod
import celerlite.api.routes.metrics as metrics_route_mod


@pytest_asyncio.fixture
async def test_app():
    # Setup in-memory SQLite database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def override_get_session():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Patch get_session in routes
    db_mod.get_session = override_get_session
    tasks_route_mod.get_session = override_get_session
    dlq_route_mod.get_session = override_get_session
    workers_route_mod.get_session = override_get_session
    metrics_route_mod.get_session = override_get_session

    mock_broker = AsyncMock()
    mock_broker.enqueue = AsyncMock(return_value="celerlite:queue:default:normal")
    mock_broker.publish_event = AsyncMock()
    mock_broker.get_result = AsyncMock(return_value=None)
    mock_broker.mark_task_revoked = AsyncMock()
    mock_broker.get_redis_info = AsyncMock(return_value={"connected": True, "memory_used_mb": 12.5})
    mock_broker.get_all_queue_lengths = AsyncMock(return_value={"default": 0, "emails": 0, "high_priority": 0})
    mock_broker.client = AsyncMock()
    mock_broker.client.scan_iter = MagicMock()

    app = create_app()
    app.dependency_overrides[get_broker] = lambda: mock_broker

    yield app, mock_broker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
class TestAPIEndpoints:
    async def test_health_endpoint(self, test_app):
        app, mock_broker = test_app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "healthy"
            assert data["redis"]["connected"] is True

    async def test_submit_task_endpoint(self, test_app):
        app, mock_broker = test_app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/tasks/submit",
                json={
                    "task_name": "tasks.process_payment",
                    "args": [100, "USD"],
                    "queue": "payments",
                    "priority": 2,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "task_id" in data
            assert data["status"] == "PENDING"
            assert data["queue"] == "payments"
            mock_broker.enqueue.assert_called_once()
            mock_broker.publish_event.assert_called_once()

    async def test_get_task_not_found(self, test_app):
        app, mock_broker = test_app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/tasks/non-existent-task-id")
            assert resp.status_code == 404

    async def test_dlq_count_empty(self, test_app):
        app, mock_broker = test_app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/dlq/count")
            assert resp.status_code == 200
            assert resp.json()["count"] == 0

    async def test_dlq_list_empty(self, test_app):
        app, mock_broker = test_app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/dlq")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)
            assert len(resp.json()) == 0
