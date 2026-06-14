"""The redirect hot path.

Cache hit: 1 Redis GET + 1 background XADD, no DB session at all.
Cache miss: single point-read on the unique short_code index, then cache fill.
302 (not 301) so browsers/CDNs don't cache us out of our own analytics;
Cache-Control bounds the load tradeoff.
"""
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.core.events import emit_click
from app.models import Link
from app.observability.metrics import CACHE_OPS
from app.services.codegen import RESERVED

router = APIRouter(tags=["redirect"])


def _ua_hash(request: Request) -> str:
    ua = request.headers.get("user-agent", "")
    # privacy by design: never store raw UA or IP
    return hashlib.sha256(ua.encode()).hexdigest()[:16] if ua else ""


@router.get("/{code}")
async def redirect(
    request: Request,
    background: BackgroundTasks,
    code: str = Path(min_length=4, max_length=12, pattern=r"^[A-Za-z0-9_-]+$"),
):
    if code.lower() in RESERVED:
        raise HTTPException(status_code=404)
    app = request.app
    cache = app.state.link_cache
    settings = app.state.settings

    url = await cache.get_url(code)
    if url is not None:
        CACHE_OPS.labels(result="hit").inc()
    else:
        if await cache.is_negative_cached(code):
            CACHE_OPS.labels(result="negative").inc()
            raise HTTPException(status_code=404)
        CACHE_OPS.labels(result="miss").inc()
        async with app.state.sessionmaker() as session:
            row = (
                await session.execute(select(Link).where(Link.short_code == code))
            ).scalar_one_or_none()
        if row is None or not row.is_redirectable(datetime.now(timezone.utc)):
            await cache.set_negative(code)
            raise HTTPException(status_code=404)
        url = row.long_url
        await cache.set_url(code, url)

    background.add_task(emit_click, app.state.redis, settings, code, _ua_hash(request))
    return RedirectResponse(
        url, status_code=302, headers={"Cache-Control": "private, max-age=90"}
    )
