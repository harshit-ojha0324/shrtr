"""The redirect hot path.

Cache hit: 1 Redis GET + 1 background XADD, no DB session at all.
Cache miss: per-IP token bucket, then a single point-read on the unique
short_code index, then cache fill.
302 (not 301) so browsers/CDNs don't cache us out of our own analytics;
Cache-Control bounds the load tradeoff.
/{code}+ resolves the same way but shows where the link goes instead.
"""
from datetime import datetime, timezone
from html import escape
from string import Template
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.exceptions import RedisError
from sqlalchemy import select

from app.core.events import emit_click
from app.models import Link
from app.observability.metrics import CACHE_OPS
from app.services.codegen import is_valid_alias

router = APIRouter(tags=["redirect"])


async def _resolve(request: Request, code: str) -> str:
    """code -> destination via cache, else one DB point-read. 404 for unknown,
    expired or deleted codes; 429 when one IP misses too often."""
    # validate here, not via Path(...): malformed codes (favicon.ico, scanner
    # probes) should get a plain 404, not a 422 echoing pydantic internals
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
        return url
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
    await cache.set_url(code, row.long_url, expires_at=row.expires_at)
    return row.long_url


# registered before /{code}: '+' can't appear in a code, so the routes never overlap
@router.get("/{code}+", response_class=HTMLResponse)
async def preview(request: Request, code: str):
    """Where does this link go? Not a click; "Continue" goes through /{code}, which is."""
    url = await _resolve(request, code)
    parts = urlsplit(url)
    secure = parts.scheme == "https"
    page = PREVIEW.substitute(
        code=code,  # is_valid_alias passed: [A-Za-z0-9_-] only
        host=escape(parts.hostname or parts.netloc),
        url=escape(url),
        badge="ok" if secure else "warn",
        badge_text="HTTPS" if secure else "Not secure: plain http, the connection is not encrypted",
    )
    return HTMLResponse(page, headers={"Cache-Control": "private, max-age=90", "X-Robots-Tag": "noindex"})


@router.get("/{code}")
async def redirect(request: Request, background: BackgroundTasks, code: str):
    url = await _resolve(request, code)
    # privacy by design: the event is code + timestamp only, no IP/UA/referrer
    background.add_task(emit_click, request.app.state.redis, request.app.state.settings, code)
    return RedirectResponse(
        url, status_code=302, headers={"Cache-Control": "private, max-age=90"}
    )


# Same tokens as the web app (frontend/src/index.css); system dark mode only.
PREVIEW = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Where /$code goes</title>
<style>
  :root { color-scheme: light dark; --app:#fbfbfa; --card:#fff; --sunken:#f3f3f1; --ink:#121212;
    --muted:#63635f; --line:#e6e6e2; --primary:#121212; --on-primary:#fff;
    --ok:#127a43; --ok-soft:#e6f4ec; --warn:#9a5800; --warn-soft:#fdf1dc; }
  @media (prefers-color-scheme: dark) { :root { --app:#0e1014; --card:#15181e; --sunken:#1b1f27;
    --ink:#e9ebef; --muted:#9aa1ad; --line:#242832; --primary:#e9ebef; --on-primary:#0e1014;
    --ok:#4cc38a; --ok-soft:#13301f; --warn:#f0b453; --warn-soft:#33260e; } }
  body { margin:0; min-height:100vh; display:grid; place-items:center; padding:16px; box-sizing:border-box;
    background:var(--app); color:var(--ink); font:15px/1.55 ui-sans-serif, system-ui, sans-serif; }
  main { width:min(100%, 520px); background:var(--card); border:1px solid var(--line);
    border-radius:16px; padding:28px; display:grid; gap:16px; }
  .eyebrow { color:var(--muted); font-size:13px; }
  .eyebrow b, .full { font-family:ui-monospace, Menlo, monospace; }
  .eyebrow b { color:var(--ink); }
  .dest { background:var(--sunken); border:1px solid var(--line); border-radius:12px; padding:16px; }
  .host { font-size:22px; font-weight:700; overflow-wrap:anywhere; }
  .full { margin-top:6px; color:var(--muted); font-size:13px; overflow-wrap:anywhere; }
  .badge { justify-self:start; font-size:12px; font-weight:600; padding:4px 10px; border-radius:999px; }
  .ok { background:var(--ok-soft); color:var(--ok); }
  .warn { background:var(--warn-soft); color:var(--warn); }
  p { margin:0; color:var(--muted); font-size:13px; }
  a { justify-self:start; padding:10px 18px; border-radius:10px; font-weight:600; text-decoration:none;
    background:var(--primary); color:var(--on-primary); }
  a:focus-visible { outline:2px solid var(--ink); outline-offset:2px; }
</style></head>
<body><main>
  <div class="eyebrow">Short link <b>/$code</b> goes to</div>
  <div class="dest"><div class="host">$host</div><div class="full">$url</div></div>
  <span class="badge $badge">$badge_text</span>
  <p>Check this is the site you expect. Viewing this page is not counted as a click.</p>
  <a href="/$code" rel="noopener noreferrer">Continue to $host &rarr;</a>
</main></body></html>""")
