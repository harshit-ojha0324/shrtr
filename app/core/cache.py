"""Cache-aside for the redirect hot path.

- positive cache:  link:{code} -> long_url, TTL = base + uniform jitter
  (jitter de-synchronizes expiries so a batch of keys never stampedes together)
- negative cache:  404:{code} -> "1", short TTL (deletes: long-lived tombstone)
  (stops typo/scanner misses from hammering PostgreSQL)
- XFetch probabilistic early refresh: stretch, not implemented (see docs/decisions.md)
"""
import random
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.config import Settings

LINK_KEY = "link:{code}"
NEG_KEY = "404:{code}"


class LinkCache:
    def __init__(self, redis: Redis, settings: Settings):
        self.redis = redis
        self.settings = settings
        self._neg_if_uncached = redis.register_script(
            "if redis.call('EXISTS', KEYS[1]) == 0 then redis.call('SET', KEYS[2], '1', 'EX', ARGV[1]) end"
        )

    async def lookup(self, code: str) -> tuple[str | None, bool]:
        """(cached url, negative-cached?) in one round trip. Callers must let the
        negative entry win: a redirect that read the DB just before a delete can
        still write a stale positive entry after the delete's tombstone."""
        url, neg = await self.redis.mget(LINK_KEY.format(code=code), NEG_KEY.format(code=code))
        return url, neg is not None

    async def set_url(self, code: str, url: str, expires_at: datetime | None = None) -> None:
        """Cache a redirect. TTL is clamped to the link's remaining lifetime so an
        expiring link can never keep redirecting from cache past expires_at."""
        ttl = self.settings.cache_ttl_seconds + random.randint(0, self.settings.cache_jitter_seconds)
        if expires_at is not None:
            remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
            if remaining <= 1:
                return  # about to expire: not worth caching
            ttl = min(ttl, remaining)
        await self.redis.set(LINK_KEY.format(code=code), url, ex=ttl)

    async def set_negative_if_uncached(self, code: str) -> None:
        """Redirect miss: negative-cache the code unless a positive entry exists,
        atomically. A miss that read the DB just before a create committed would
        otherwise 404 the new link for the negative TTL; create warms the
        positive entry first (see publish), so this write becomes a no-op."""
        await self._neg_if_uncached(
            keys=[LINK_KEY.format(code=code), NEG_KEY.format(code=code)],
            args=[self.settings.negative_cache_ttl_seconds],
        )

    async def publish(self, code: str, url: str, expires_at: datetime | None = None) -> None:
        """On create: warm the positive entry, THEN drop any stale negative one."""
        await self.set_url(code, url, expires_at)
        await self.redis.delete(NEG_KEY.format(code=code))

    async def tombstone(self, code: str) -> None:
        """On delete: a negative entry that outlives any positive entry a racing
        redirect could still write (max positive TTL = base + jitter)."""
        await self.redis.delete(LINK_KEY.format(code=code))
        ttl = self.settings.cache_ttl_seconds + self.settings.cache_jitter_seconds
        await self.redis.set(NEG_KEY.format(code=code), "1", ex=ttl)
