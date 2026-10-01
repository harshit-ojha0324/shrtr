"""Structured configuration from environment variables (12-factor style)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core services
    database_url: str = "postgresql+asyncpg://shrtr:shrtr@localhost:5432/shrtr"
    redis_url: str = "redis://localhost:6379/0"
    base_url: str = "http://localhost:8000"

    # Redis connection pool (API): blocking pool so bursts queue briefly
    # instead of erroring when all connections are checked out
    redis_max_connections: int = 200
    redis_pool_timeout_s: float = 2.0

    # Cache (MVP: cache-aside with TTL jitter + negative caching)
    cache_ttl_seconds: int = 86400
    cache_jitter_seconds: int = 3600
    negative_cache_ttl_seconds: int = 300

    # Rate limiting defaults (per API key; overridable per key in DB)
    rate_capacity_default: int = 60
    rate_refill_per_s_default: float = 1.0

    # Redis Streams analytics pipeline
    stream_key: str = "clicks"
    stream_group: str = "analytics"
    stream_maxlen: int = 1_000_000
    dlq_key: str = "clicks:dlq"
    dlq_maxlen: int = 10_000
    worker_batch_size: int = 100
    worker_block_ms: int = 5000
    worker_reclaim_min_idle_ms: int = 60_000
    worker_metrics_port: int = 9100

    # DB pool
    db_pool_size: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
