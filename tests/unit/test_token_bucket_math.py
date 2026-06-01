"""Frozen-clock tests of the token bucket, run against the real Lua script
(fakeredis executes Lua), not a Python mirror of it.
"""
from types import SimpleNamespace

import pytest
from fakeredis import aioredis

from app.core import ratelimit
from app.core.ratelimit import RateLimiter


@pytest.fixture
def clock(monkeypatch):
    now = SimpleNamespace(s=1_000.0)
    monkeypatch.setattr(ratelimit, "time", SimpleNamespace(time=lambda: now.s))
    return now


@pytest.fixture
def limiter():
    return RateLimiter(aioredis.FakeRedis(decode_responses=True))


async def test_fresh_bucket_starts_full(clock, limiter):
    d = await limiter.take(1, capacity=10, refill_per_s=1.0)
    assert d.allowed and d.remaining == 9.0


async def test_exhaustion_at_capacity_plus_one(clock, limiter):
    results = [(await limiter.take(1, capacity=10, refill_per_s=1.0)) for _ in range(11)]  # same instant
    assert [d.allowed for d in results] == [True] * 10 + [False]  # request capacity+1 rejected
    assert results[-1].retry_after_s == 1


async def test_refill_over_time(clock, limiter):
    for _ in range(10):
        await limiter.take(1, capacity=10, refill_per_s=2.0)
    assert not (await limiter.take(1, capacity=10, refill_per_s=2.0)).allowed
    clock.s += 1.5  # -> 3 tokens refilled
    d = await limiter.take(1, capacity=10, refill_per_s=2.0)
    assert d.allowed and d.remaining == 2.0


async def test_refill_never_exceeds_capacity(clock, limiter):
    await limiter.take(1, capacity=10, refill_per_s=100.0)
    clock.s += 60
    d = await limiter.take(1, capacity=10, refill_per_s=100.0)
    assert d.remaining == 9.0  # capped at 10, then one consumed


async def test_clock_going_backwards_is_safe(clock, limiter):
    await limiter.take(1, capacity=10, refill_per_s=1.0)
    clock.s -= 5
    d = await limiter.take(1, capacity=10, refill_per_s=1.0)
    assert d.allowed and d.remaining == 8.0  # no negative refill


async def test_retry_after_is_a_ceiling(clock, limiter):
    await limiter.take(1, capacity=1, refill_per_s=0.4)
    d = await limiter.take(1, capacity=1, refill_per_s=0.4)
    assert not d.allowed and d.retry_after_s == 3  # 1 / 0.4 = 2.5 -> 3


async def test_survives_redis_script_cache_flush(clock, limiter):
    await limiter.take(1, capacity=10, refill_per_s=1.0)
    await limiter._take.registered_client.script_flush()  # what a Redis restart does
    assert (await limiter.take(1, capacity=10, refill_per_s=1.0)).remaining == 8.0
