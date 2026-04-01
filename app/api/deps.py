"""Dependency chain: API key auth -> rate limit -> handler.

Rate-limit failure policy when Redis is down (deliberate, documented):
- mutating requests (POST/DELETE) fail CLOSED (503) -> protect PostgreSQL writes
- read requests (GET) fail OPEN -> availability for harmless reads
"""
import hashlib
import time

from fastapi import Depends, Header, HTTPException, Request
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey
from app.observability.metrics import RATE_LIMIT_DECISIONS

_KEY_CACHE: dict[str, tuple[float, ApiKey]] = {}
_KEY_CACHE_TTL_S = 60.0


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_session(request: Request) -> AsyncSession:
    async with request.app.state.sessionmaker() as session:
        yield session


async def require_api_key(
    request: Request,
    x_api_key: str = Header(..., description="Raw API key; only its SHA-256 is stored server-side"),
) -> ApiKey:
    digest = hash_key(x_api_key)
    cached = _KEY_CACHE.get(digest)
    if cached and time.monotonic() - cached[0] < _KEY_CACHE_TTL_S:
        return cached[1]
    async with request.app.state.sessionmaker() as session:
        row = (await session.execute(select(ApiKey).where(ApiKey.key_hash == digest))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    _KEY_CACHE[digest] = (time.monotonic(), row)
    return row


async def rate_limit(request: Request, api_key: ApiKey = Depends(require_api_key)) -> ApiKey:
    limiter = request.app.state.rate_limiter
    try:
        decision = await limiter.take(api_key.id, api_key.rate_capacity, api_key.refill_per_s)
    except RedisError:
        if request.method in ("POST", "DELETE", "PUT", "PATCH"):
            raise HTTPException(status_code=503, detail="rate limiter unavailable; writes are paused")
        return api_key  # fail open for reads
    RATE_LIMIT_DECISIONS.labels(allowed=str(decision.allowed).lower()).inc()
    headers = {
        "X-RateLimit-Limit": str(decision.capacity),
        "X-RateLimit-Remaining": str(max(0, int(decision.remaining))),
    }
    if not decision.allowed:
        headers["Retry-After"] = str(decision.retry_after_s)
        raise HTTPException(status_code=429, detail="rate limit exceeded", headers=headers)
    request.state.rate_headers = headers
    return api_key
