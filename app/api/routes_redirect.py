"""The redirect hot path.

Cache hit: 1 Redis GET + 1 background XADD, no DB session at all.
Cache miss: per-IP token bucket, then a single point-read on the unique
short_code index, then cache fill.
302 (not 301) so browsers/CDNs don't cache us out of our own analytics;
Cache-Control bounds the load tradeoff.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse
from redis.exceptions import RedisError
from sqlalchemy import select

from app.core.events import emit_click
from app.models import Link
from app.observability.metrics import CACHE_OPS
from app.services.codegen import is_valid_alias

router = APIRouter(tags=["redirect"])


@router.get("/{code}")
async def redirect(request: Request, background: BackgroundTasks, code: str):
    # validate in the handler, not via Path(...): malformed codes (favicon.ico,
    # scanner probes) should get a plain 404, not a 422 echoing pydantic internals
    if not is_valid_alias(code):
        raise HTTPException(status_code=404)
    app = request.app
    cache = app.state.link_cache
    settings = app.state.settings

    url, negative = await cache.lookup(code)
    if negative:  # checked first: wins over a stale positive entry (see LinkCache.lookup)
        CACHE_OPS.labels(result="negative").inc()
        raise HTTPException(status_code=404)
    if url is not None:
        CACHE_OPS.labels(result="hit").inc()
    else:
        CACHE_OPS.labels(result="miss").inc()
        # misses are what cost a DB read (+ a negative key): cap them per client IP
        # so random-code scans can't hammer PostgreSQL. Hits stay one Redis call.
        # Behind a proxy, run uvicorn with --proxy-headers so client.host is real.
        ip = request.client.host if request.client else "unknown"
        try:
            d = await app.state.rate_limiter.take(
                f"ip:{ip}", settings.redirect_miss_capacity, settings.redirect_miss_refill_per_s
            )
        except RedisError:
            d = None  # fail open: redirects are reads (same policy as api/deps.py)
        if d is not None and not d.allowed:
            raise HTTPException(status_code=429, headers={"Retry-After": str(d.retry_after_s)})
        async with app.state.sessionmaker() as session:
            row = (
                await session.execute(select(Link).where(Link.short_code == code))
            ).scalar_one_or_none()
        if row is None or not row.is_redirectable(datetime.now(timezone.utc)):
            await cache.set_negative_if_uncached(code)
            raise HTTPException(status_code=404)
        url = row.long_url
        await cache.set_url(code, url, expires_at=row.expires_at)

    # privacy by design: the event is code + timestamp only, no IP/UA/referrer
    background.add_task(emit_click, app.state.redis, settings, code)
    return RedirectResponse(
        url, status_code=302, headers={"Cache-Control": "private, max-age=90"}
    )
