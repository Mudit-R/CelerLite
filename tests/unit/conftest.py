"""Shared fixtures for CRM unit tests."""

import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from celerlite.api.app import create_app
from celerlite.persistence.models import Base
import celerlite.persistence.database as db_mod
import celerlite.api.routes.crm as crm_route_mod


import celerlite.api.routes.tasks as task_route_mod


@pytest_asyncio.fixture
async def crm_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def crm_app(monkeypatch):
    monkeypatch.setattr('celerlite.config.config.AUTH_REQUIRED', False)
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

    monkeypatch.setattr(db_mod, "get_session", override_get_session)
    monkeypatch.setattr(crm_route_mod, "get_session", override_get_session)
    monkeypatch.setattr(task_route_mod, "get_session", override_get_session)

    app = create_app(serverless=True)
    yield app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
