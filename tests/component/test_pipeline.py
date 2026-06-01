"""Component tests: the FULL pipeline in one process, no Docker required.

SQLite stands in for PostgreSQL (same SQLAlchemy models, dialect-aware upserts)
and fakeredis (with real Lua) stands in for Redis. PostgreSQL-specific behavior
is additionally covered by tests/integration against the compose stack.

Covers: create -> redirect (cache miss/hit) -> stream -> worker batch ->
hourly rollups -> stats API; idempotent replay; DLQ for poison events;
cache-aside DB-query counting; negative caching; token-bucket 429s.
"""
import asyncio
import hashlib

import pytest
from fakeredis import aioredis as fakeaio
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.cache import LinkCache
from app.core.ratelimit import RateLimiter
from app.main import create_app
from app.models import ApiKey, Base, ClickRollupHourly, ProcessedEvent
from workers.analytics import AnalyticsWorker

RAW_KEY = "component-test-key"
HEADERS = {"X-API-Key": RAW_KEY}


@pytest.fixture()
def stack():
    """App wired to in-memory sqlite + fakeredis, plus a worker on the same stores.

    One explicit event loop is shared by the fixture setup, the run() helper,
    and the loop-bound async objects (aiosqlite engine, fakeredis)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = create_app()
    engine = create_async_engine("sqlite+aiosqlite://")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = fakeaio.FakeRedis(decode_responses=True)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as s:
            s.add(
                ApiKey(
                    key_hash=hashlib.sha256(RAW_KEY.encode()).hexdigest(),
                    name="component",
                    # refill must be slow enough that the wall clock cannot re-earn
                    # tokens during the 40-request burst test (30/s made the 429
                    # disappear whenever the loop averaged >~8.5ms/request)
                    rate_capacity=30,
                    refill_per_s=0.5,
                )
            )
            await s.commit()

    loop.run_until_complete(setup())

    # count SELECTs so we can prove cache hits skip the database
    sql_counter = {"selects": 0}

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, *a, **kw):
        if statement.lstrip().upper().startswith("SELECT"):
            sql_counter["selects"] += 1

    with TestClient(app) as client:
        app.state.engine = engine
        app.state.sessionmaker = sessions
        app.state.redis = redis
        app.state.link_cache = LinkCache(redis, get_settings())
        app.state.rate_limiter = RateLimiter(redis)

        worker = AnalyticsWorker.__new__(AnalyticsWorker)  # skip __init__ (no real conns)
        worker.settings = get_settings()
        worker.name = "test-worker"
        worker.redis = redis
        worker.engine = engine
        worker.sessions = sessions
        worker.shutting_down = False
        worker._link_id_cache = {}

        yield client, redis, sessions, worker, sql_counter

    asyncio.set_event_loop(None)
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def read_batch(worker):
    resp = await worker.redis.xreadgroup(
        worker.settings.stream_group, worker.name, {worker.settings.stream_key: ">"}, count=100, block=10
    )
    return resp[0][1] if resp else []


def test_full_pipeline_and_idempotency(stack):
    client, redis, sessions, worker, sql_counter = stack

    code = client.post("/api/v1/links", json={"long_url": "https://example.com/p"}, headers=HEADERS).json()[
        "short_code"
    ]

    # redirect 3x: first is a cache miss (1 DB select), next two are pure cache hits
    assert client.get(f"/{code}", follow_redirects=False).status_code == 302
    selects_after_miss = sql_counter["selects"]
    for _ in range(2):
        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "https://example.com/p"
    assert sql_counter["selects"] == selects_after_miss, "cache hit must not query the DB"

    assert run(redis.xlen("clicks")) == 3  # events published

    # worker consumes and rolls up
    run(worker.ensure_group())
    entries = run(read_batch(worker))
    assert len(entries) == 3
    run(worker.process_batch(entries))

    async def totals():
        async with sessions() as s:
            clicks = (await s.execute(select(ClickRollupHourly.clicks))).scalars().all()
            ledger = (await s.execute(select(ProcessedEvent.event_id))).scalars().all()
            return sum(clicks), len(ledger)

    assert run(totals()) == (3, 3)

    # IDEMPOTENCY: replaying the exact same entries must not change counts
    run(worker.process_batch(entries))
    assert run(totals()) == (3, 3)

    # stats endpoint sees the rollups
    stats = client.get(f"/api/v1/links/{code}/stats?granularity=hour", headers=HEADERS).json()
    assert stats["total_clicks"] == 3


def test_poison_event_goes_to_dlq(stack):
    client, redis, sessions, worker, _ = stack
    run(worker.ensure_group())
    run(redis.xadd("clicks", {"garbage": "no code or ts"}))
    entries = run(read_batch(worker))
    run(worker.process_batch(entries))
    assert run(redis.xlen(worker.settings.dlq_key)) == 1
    # poison entry was acked away: nothing pending
    pending = run(redis.xpending("clicks", worker.settings.stream_group))
    assert (pending.get("pending") if isinstance(pending, dict) else pending) == 0


def test_negative_cache_blocks_second_db_lookup(stack):
    client, _, _, _, sql_counter = stack
    assert client.get("/nope999", follow_redirects=False).status_code == 404
    before = sql_counter["selects"]
    assert client.get("/nope999", follow_redirects=False).status_code == 404
    assert sql_counter["selects"] == before, "second 404 must be served by the negative cache"


def test_rate_limit_burst_429(stack):
    client, _, _, _, _ = stack
    first = client.get("/api/v1/links?limit=1", headers=HEADERS)
    assert first.status_code == 200  # burst allowed up to capacity first
    # X-RateLimit-* headers (advertised in the README) on an allowed response
    assert first.headers["X-RateLimit-Limit"] == "30"
    assert first.headers["X-RateLimit-Remaining"] == "29"

    statuses = [first.status_code] + [
        client.get("/api/v1/links?limit=1", headers=HEADERS).status_code for _ in range(39)
    ]
    assert 429 in statuses and statuses.index(429) > 0

    # refill is 0.5 tokens/s, so the wall clock cannot re-earn a token during
    # the burst: the follow-up request is deterministically limited too
    r = client.get("/api/v1/links?limit=1", headers=HEADERS)
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}
    assert r.headers["X-RateLimit-Remaining"] == "0"


def test_delete_beats_racing_stale_cache_write(stack):
    client, _, _, _, _ = stack
    code = client.post("/api/v1/links", json={"long_url": "https://example.com/r"}, headers=HEADERS).json()[
        "short_code"
    ]
    assert client.delete(f"/api/v1/links/{code}", headers=HEADERS).status_code == 204
    # a redirect that read the still-active row just before the delete commits
    # finishes its cache fill AFTER the delete's invalidate
    run(client.app.state.link_cache.set_url(code, "https://example.com/r"))
    assert client.get(f"/{code}", follow_redirects=False).status_code == 404
    # and the tombstone outlives any positive TTL that write could have had
    s = get_settings()
    assert run(client.app.state.redis.ttl(f"404:{code}")) > s.cache_ttl_seconds


def test_negative_limit_is_422_not_500(stack):
    client, _, _, _, _ = stack
    # PostgreSQL rejects LIMIT -1 (SQLite silently allows it), so validate at the edge
    assert client.get("/api/v1/links?limit=-1", headers=HEADERS).status_code == 422


def test_metrics_endpoint(stack):
    client, _, _, _, _ = stack
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    for series in (
        "http_request_duration_seconds",
        "cache_ops_total",
        "rate_limit_decisions_total",
        "clicks_published_total",
    ):
        assert series in body
