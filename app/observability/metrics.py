"""Prometheus metrics: API side."""
import time

from prometheus_client import Counter, Histogram
from starlette.requests import Request

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["route", "method", "status"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
)
CACHE_OPS = Counter("cache_ops_total", "Link cache lookups", ["result"])  # hit|miss|negative
RATE_LIMIT_DECISIONS = Counter("rate_limit_decisions_total", "Token bucket decisions", ["allowed"])
CLICKS_PUBLISHED = Counter("clicks_published_total", "Click events published to the stream")
CLICKS_DROPPED = Counter("clicks_dropped_total", "Click events dropped (Redis unavailable)")
API_ERRORS = Counter("api_errors_total", "Unhandled API errors", ["route"])


async def latency_middleware(request: Request, call_next):
    start = time.perf_counter()
    status = "500"
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    except Exception:
        route = getattr(request.scope.get("route"), "path", request.url.path)
        API_ERRORS.labels(route=route).inc()
        raise
    finally:
        route = getattr(request.scope.get("route"), "path", request.url.path)
        REQUEST_LATENCY.labels(route=route, method=request.method, status=status).observe(
            time.perf_counter() - start
        )
