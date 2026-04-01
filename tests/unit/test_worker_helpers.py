from datetime import datetime, timezone

from app.core.cache import ttl_with_jitter
from workers.analytics import hour_floor


def test_hour_floor():
    ts = datetime(2026, 6, 12, 13, 47, 31, tzinfo=timezone.utc).timestamp() * 1000
    assert hour_floor(int(ts)) == datetime(2026, 6, 12, 13, 0, 0, tzinfo=timezone.utc)


def test_hour_floor_is_utc():
    assert hour_floor(0) == datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_ttl_jitter_range():
    values = {ttl_with_jitter(100, 50) for _ in range(500)}
    assert all(100 <= v <= 150 for v in values)
    assert len(values) > 10  # actually jittering, not constant
