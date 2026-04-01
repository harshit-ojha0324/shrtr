"""Frozen-clock tests of the token-bucket refill math.

compute_take() is the pure-Python mirror of the Lua script; the Lua script's
behavior against real Redis is covered by the integration suite.
"""
from app.core.ratelimit import compute_take


def test_fresh_bucket_starts_full():
    allowed, remaining = compute_take(None, None, capacity=10, refill_per_s=1.0, now_ms=0)
    assert allowed and remaining == 9.0


def test_exhaustion_at_capacity_plus_one():
    tokens, ts = None, None
    now = 1_000_000
    results = []
    for _ in range(11):
        allowed, tokens = compute_take(tokens, ts, capacity=10, refill_per_s=1.0, now_ms=now)
        ts = now  # same instant: no refill between calls
        results.append(allowed)
    assert results[:10] == [True] * 10
    assert results[10] is False  # request capacity+1 rejected


def test_refill_over_time():
    # drain the bucket
    tokens, ts = 0.0, 1_000_000
    allowed, tokens = compute_take(tokens, ts, capacity=10, refill_per_s=2.0, now_ms=1_000_000)
    assert not allowed
    # 1.5s later -> 3 tokens refilled
    allowed, tokens = compute_take(tokens, 1_000_000, capacity=10, refill_per_s=2.0, now_ms=1_001_500)
    assert allowed
    assert tokens == 2.0


def test_refill_never_exceeds_capacity():
    allowed, tokens = compute_take(5.0, 0, capacity=10, refill_per_s=100.0, now_ms=60_000)
    assert allowed
    assert tokens == 9.0  # capped at 10, then one consumed


def test_clock_going_backwards_is_safe():
    allowed, tokens = compute_take(5.0, 10_000, capacity=10, refill_per_s=1.0, now_ms=5_000)
    assert allowed
    assert tokens == 4.0  # no negative refill
