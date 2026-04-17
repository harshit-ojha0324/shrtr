"""Cache-aside for the redirect hot path.

- positive cache:  link:{code} -> long_url, TTL = base + uniform jitter
  (jitter de-synchronizes expiries so a batch of keys never stampedes together)
- negative cache:  404:{code} -> "1", short TTL
  (stops typo/scanner misses from hammering PostgreSQL)
- XFetch probabilistic early refresh: stretch, not implemented (see docs/decisions.md)
"""
import random
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.config import Settings

LINK_KEY = "link:{code}"
NEG_KEY = "404:{code}"


def ttl_with_jitter(base: int, jitter: int) -> int:
    return base + random.randint(0, jitter)


class LinkCache:
    def __init__(self, redis: Redis, settings: Settings):
        self.redis = redis
        self.settings = settings

    async def get_url(self, code: str) -> str | None:
        return await self.redis.get(LINK_KEY.format(code=code))

    async def set_url(self, code: str, url: str, expires_at: datetime | None = None) -> None:
        """Cache a redirect. TTL is clamped to the link's remaining lifetime so an
        expiring link can never keep redirecting from cache past expires_at."""
        ttl = ttl_with_jitter(self.settings.cache_ttl_seconds, self.settings.cache_jitter_seconds)
        if expires_at is not None:
            remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
            if remaining <= 1:
                return  # about to expire: not worth caching
            ttl = min(ttl, remaining)
        await self.redis.set(LINK_KEY.format(code=code), url, ex=ttl)

    async def is_negative_cached(self, code: str) -> bool:
        return await self.redis.get(NEG_KEY.format(code=code)) is not None

    async def set_negative(self, code: str) -> None:
        await self.redis.set(NEG_KEY.format(code=code), "1", ex=self.settings.negative_cache_ttl_seconds)

    async def invalidate(self, code: str) -> None:
        """On delete: drop positive entry. On create: drop stale negative entry."""
        await self.redis.delete(LINK_KEY.format(code=code), NEG_KEY.format(code=code))
