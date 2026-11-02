"""Async SQLAlchemy engine and session factory with automatic SQLite fallback."""

import os
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.engine import make_url

from celerlite.config import config
from celerlite.observability.logger import get_logger
from sqlalchemy.pool import NullPool
from celerlite.persistence.models import Base

logger = get_logger(__name__)


def _normalize_async_url(url: str) -> str:
    """Select the async SQLAlchemy driver for common Postgres/SQLite URLs."""
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend in ("postgres", "postgresql") and parsed.drivername != "postgresql+asyncpg":
        parsed = parsed.set(drivername="postgresql+asyncpg")
    elif backend == "sqlite" and parsed.drivername == "sqlite":
        parsed = parsed.set(drivername="sqlite+aiosqlite")
    return parsed.render_as_string(hide_password=False)


def _create_engine(url: str):
    url = _normalize_async_url(url)
    if "sqlite" in url:
        return create_async_engine(url, poolclass=NullPool, echo=False)
    return create_async_engine(
        url,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
        echo=False,
    )


# In Vercel serverless / read-only filesystem environments, default directly to SQLite in /tmp
_is_vercel = bool(
    os.environ.get("VERCEL")
    or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    or os.environ.get("VERCEL_ENV")
)


def _get_initial_db_url() -> str:
    explicit = os.environ.get("CELERLITE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    if _is_vercel:
        return "sqlite+aiosqlite:////tmp/celerlite_dev.db"
    return config.DATABASE_URL


_initial_db_url = _normalize_async_url(_get_initial_db_url())

engine = _create_engine(_initial_db_url)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

_db_initialized = False
_demo_engine = None
_demo_session_local = None
_demo_db_url = ""
_demo_db_initialized = False
_database_target: ContextVar[str] = ContextVar("celerlite_database_target", default="private")


def demo_database_isolated() -> bool:
    """Whether demo reads are routed to a distinct database from private records."""
    demo_url = config.DEMO_DATABASE_URL.strip()
    if not demo_url:
        return False

    def identity(url: str):
        parsed = make_url(url)
        dialect = parsed.get_backend_name()
        if dialect == "postgres":
            dialect = "postgresql"
        if dialect == "sqlite":
            database = parsed.database or ":memory:"
            path = database if database == ":memory:" else os.path.normcase(os.path.abspath(database))
            return dialect, path
        if dialect == "postgresql":
            # Treat the same Postgres database name as the same identity even
            # when internal/external hostnames or credentials differ. This is
            # intentionally conservative: demo storage should have its own DB.
            return dialect, (parsed.database or "").casefold()
        # Ignore driver and credentials so equivalent URLs cannot masquerade
        # as separate databases.
        return dialect, parsed.host, parsed.port, parsed.database

    try:
        demo_identity = identity(demo_url)
        private_urls = {
            str(engine.url),
            _initial_db_url,
            config.DATABASE_URL,
            os.environ.get("CELERLITE_DATABASE_URL", ""),
            os.environ.get("DATABASE_URL", ""),
        }

        # If the configured private Postgres database fails during startup,
        # init_db() falls back to this exact SQLite location. Include it even
        # before initialization so a colliding demo override never races that
        # fallback and becomes an alias for private records.
        if any(identity(url)[0] == "postgresql" for url in private_urls if url):
            fallback_path = "/tmp/celerlite_dev.db" if _is_vercel else "./celerlite_dev.db"
            private_urls.add(f"sqlite+aiosqlite:///{fallback_path}")

        return all(identity(url) != demo_identity for url in private_urls if url)
    except (ValueError, TypeError):
        return False


@contextmanager
def use_demo_database():
    """Route database sessions created in this request/task context to demo data."""
    token = _database_target.set("demo")
    try:
        yield
    finally:
        _database_target.reset(token)


async def init_db() -> None:
    """Create all tables. Automatically falls back to SQLite if PostgreSQL is unreachable."""
    global engine, AsyncSessionLocal, _db_initialized
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _db_initialized = True
        logger.info("db_initialized", url=str(engine.url))
    except Exception as e:
        if "postgresql" in str(engine.url):
            logger.warning(
                "postgres_unavailable_fallback_sqlite",
                msg="PostgreSQL unreachable. Falling back to SQLite database.",
                error=str(e),
            )
            db_path = "/tmp/celerlite_dev.db" if _is_vercel else "./celerlite_dev.db"
            sqlite_url = f"sqlite+aiosqlite:///{db_path}"
            engine = _create_engine(sqlite_url)
            AsyncSessionLocal = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            _db_initialized = True
            logger.info("db_fallback_sqlite_initialized", url=sqlite_url)
        else:
            raise


async def ensure_demo_db_ready() -> None:
    """Initialize the isolated synthetic-data database when configured."""
    global _demo_engine, _demo_session_local, _demo_db_url, _demo_db_initialized
    url = config.DEMO_DATABASE_URL.strip()
    if not url or not demo_database_isolated():
        raise RuntimeError("An isolated demo database is not configured")
    if _demo_engine is None or _demo_db_url != url:
        if _demo_engine is not None:
            await _demo_engine.dispose()
        _demo_engine = _create_engine(url)
        _demo_session_local = async_sessionmaker(
            _demo_engine, class_=AsyncSession, expire_on_commit=False
        )
        _demo_db_url = url
        _demo_db_initialized = False
    if not _demo_db_initialized:
        async with _demo_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _demo_db_initialized = True
        logger.info("demo_db_initialized", url=str(_demo_engine.url))


async def init_demo_db() -> None:
    """Initialize the demo database during application startup."""
    await ensure_demo_db_ready()


async def ensure_db_ready() -> None:
    """Ensure database tables are created (essential for serverless where lifespan may not run)."""
    global _db_initialized
    if not _db_initialized:
        await init_db()


async def drop_db() -> None:
    """Drop all tables (for testing teardown)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager for a database session with lazy initialization."""
    if _database_target.get() == "demo":
        await ensure_demo_db_ready()
        session_factory = _demo_session_local
    else:
        await ensure_db_ready()
        session_factory = AsyncSessionLocal
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
