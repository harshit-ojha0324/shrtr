"""Click-event producer (Redis Streams).

Deliberate tradeoff (documented): events are emitted via FastAPI BackgroundTasks
*after* the redirect response, so analytics never adds latency to the hot path.
A crash in that window loses one click event; the drop counter makes the loss visible.
For billing-grade events you would emit before responding instead.
"""
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings
from app.observability.metrics import CLICKS_DROPPED, CLICKS_PUBLISHED


async def emit_click(
    redis: Redis, settings: Settings, code: str, ua_hash: str = "", referrer: str = ""
) -> None:
    try:
        await redis.xadd(
            settings.stream_key,
            {"code": code, "ts": str(int(time.time() * 1000)), "ua": ua_hash, "ref": referrer[:256]},
            maxlen=settings.stream_maxlen,
            approximate=True,
        )
        CLICKS_PUBLISHED.inc()
    except RedisError:
        # Drop analytics rather than fail redirects; visible via metric.
        CLICKS_DROPPED.inc()
