from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis

from app.api import routes_health, routes_links, routes_redirect
from app.config import get_settings
from app.core.cache import LinkCache
from app.core.ratelimit import RateLimiter
from app.db.session import make_engine, make_sessionmaker
from app.observability.metrics import latency_middleware


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.link_cache = LinkCache(app.state.redis, settings)
        app.state.rate_limiter = RateLimiter(app.state.redis)
        try:
            await app.state.rate_limiter.load()
        except Exception:
            pass  # lazy-loaded on first use if Redis wasn't up yet
        yield
        await app.state.redis.aclose()
        await app.state.engine.dispose()

    app = FastAPI(title="shrtr", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(latency_middleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(routes_health.router)
    app.include_router(routes_links.router)
    # bare /{code} registered LAST so it can't shadow the routes above
    app.include_router(routes_redirect.router)
    return app


app = create_app()
