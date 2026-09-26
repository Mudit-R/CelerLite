"""Central configuration for CelerLite using environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class CelerLiteConfig(BaseSettings):
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 20

    # PostgreSQL
    DATABASE_URL: str = (
        "postgresql+asyncpg://celerlite:celerlite@localhost:5432/celerlite"
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Worker
    WORKER_CONCURRENCY: int = 4
    WORKER_PREFETCH_MULTIPLIER: int = 1
    TASK_DEFAULT_TIMEOUT: int = 300
    TASK_ACK_LATE: bool = True

    # Retry
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: float = 2.0
    RETRY_BACKOFF_MAX: float = 3600.0
    RETRY_JITTER: bool = True

    # Heartbeat
    HEARTBEAT_INTERVAL: int = 10
    HEARTBEAT_TIMEOUT: int = 30

    # Rate Limiting
    RATE_LIMIT_DEFAULT: int = 0  # 0 = unlimited

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Result TTL
    RESULT_TTL: int = 86400  # 24 hours

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    model_config = SettingsConfigDict(
        env_prefix="CELERLITE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Singleton config instance
config = CelerLiteConfig()
