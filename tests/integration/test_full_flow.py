"""End-to-end integration tests against the running docker compose stack.

Run:
    make up && make seed   # note the printed API key
    SEED_API_KEY=<key> INTEGRATION=1 pytest tests/integration -q

Skipped automatically unless INTEGRATION=1.
"""
import asyncio
import os
import time

import httpx
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("INTEGRATION") != "1", reason="set INTEGRATION=1 with stack running"),
]

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("SEED_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def test_health(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_create_redirect_stats_roundtrip(client):
    r = client.post("/api/v1/links", json={"long_url": "https://example.com/it"}, headers=HEADERS)
    assert r.status_code == 201, r.text
    code = r.json()["short_code"]

    # redirect twice (first = cache miss, second = hit)
    for _ in range(2):
        rr = client.get(f"/{code}", follow_redirects=False)
        assert rr.status_code == 302
        assert rr.headers["location"] == "https://example.com/it"

    # analytics is async; poll stats until the worker catches up
    deadline = time.time() + 15
    total = 0
    while time.time() < deadline:
        s = client.get(f"/api/v1/links/{code}/stats", headers=HEADERS)
        assert s.status_code == 200
        total = s.json()["total_clicks"]
        if total >= 2:
            break
        time.sleep(0.5)
    assert total >= 2, "worker did not roll up clicks within 15s"


def test_delete_stops_redirects(client):
    r = client.post("/api/v1/links", json={"long_url": "https://example.com/del"}, headers=HEADERS)
    code = r.json()["short_code"]
    assert client.get(f"/{code}", follow_redirects=False).status_code == 302
    assert client.delete(f"/api/v1/links/{code}", headers=HEADERS).status_code == 204
    assert client.get(f"/{code}", follow_redirects=False).status_code == 404


def test_unknown_code_404_and_negative_cache(client):
    assert client.get("/zzzzzz9", follow_redirects=False).status_code == 404
    assert client.get("/zzzzzz9", follow_redirects=False).status_code == 404  # served by negative cache


def test_auth_required(client):
    assert client.post("/api/v1/links", json={"long_url": "https://example.com"}).status_code in (401, 422)
    assert client.get("/api/v1/links", headers={"X-API-Key": "wrong"}).status_code == 401


def test_rate_limit_eventually_429(client):
    """Demo key: capacity 60, refill 1/s -> a fast burst of 80 reads must hit 429."""
    saw_429 = False
    for _ in range(80):
        r = client.get("/api/v1/links?limit=1", headers=HEADERS)
        if r.status_code == 429:
            saw_429 = True
            assert "Retry-After" in r.headers
            assert "X-RateLimit-Remaining" in r.headers
            break
    assert saw_429, "burst of 80 requests never hit the rate limit"
    # be polite to subsequent tests
    asyncio.run(asyncio.sleep(2))
