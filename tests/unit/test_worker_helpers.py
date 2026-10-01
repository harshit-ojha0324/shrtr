from datetime import datetime, timezone

from workers.analytics import hour_floor


def test_hour_floor():
    ts = datetime(2026, 6, 12, 13, 47, 31, tzinfo=timezone.utc).timestamp() * 1000
    assert hour_floor(int(ts)) == datetime(2026, 6, 12, 13, 0, 0, tzinfo=timezone.utc)


def test_hour_floor_is_utc():
    assert hour_floor(0) == datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)
