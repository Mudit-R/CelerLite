"""Async SQLAlchemy engine and session factory with automatic SQLite fallback."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from celerlite.config import config
from celerlite.observability.logger import get_logger
from celerlite.persistence.models import Base

logger = get_logger(__name__)


def _create_engine(url: str):
    if "sqlite" in url:
        return create_async_engine(url, echo=False)
    return create_async_engine(
        url,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
        echo=False,
    )


engine = _create_engine(config.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create all tables. Automatically falls back to SQLite if PostgreSQL is unreachable."""
    global engine, AsyncSessionLocal
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("db_initialized", url=str(engine.url))
    except Exception as e:
        if "postgresql" in str(engine.url):
            logger.warning(
                "postgres_unavailable_fallback_sqlite",
                msg="PostgreSQL unreachable at localhost:5432. Falling back to local SQLite database (celerlite_dev.db)",
                error=str(e),
            )
            import os
            db_path = "/tmp/celerlite_dev.db" if os.environ.get("VERCEL") else "./celerlite_dev.db"
            sqlite_url = f"sqlite+aiosqlite:///{db_path}"
            engine = _create_engine(sqlite_url)
            AsyncSessionLocal = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("db_fallback_sqlite_initialized", url=sqlite_url)
        else:
            raise


async def drop_db() -> None:
    """Drop all tables (for testing teardown)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager for a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
