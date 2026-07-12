# Benchmark run — 2026-07-11 (late evening, local)

## Hardware / environment

- MacBook Pro, Apple **M3 Pro**, 18 GB RAM
- Docker Desktop VM: **11 CPUs, 8 GB memory**
- Everything on one machine over loopback: k6 (dockerized), api
  (1 uvicorn worker), 1 analytics worker, postgres:16, redis:7,
  prometheus, grafana
- Dataset: 10,000 seeded links (`make seed-load`); k6 picks codes with
  a Zipf-ish skew over the first 1,000 (`load/redirect_hot.js`)

## Method

`make load` → ramping-arrival-rate: ramp to 500 req/s over 1 min, hold
500 req/s for 3 min, ramp down 30 s. `redirects: 0` (we measure shrtr,
not the redirect target). Thresholds: error rate < 0.1%, p99 < 250 ms.

## Result (`k6-redirect-hot-500rps-final.json`)

- **114,000 requests, 0 failures**, all checks (status 302) passed
- Client-side latency: p50 0.87 ms · p90 1.26 ms · p95 1.5 ms ·
  avg 1.21 ms · max 168 ms
- Server-side (Prometheus histogram, 3m window at peak): p99 < 5 ms
  (first bucket boundary), cache hit ratio ~100% warm
- Consumer lag: 0 pending entries throughout; events published ≈
  processed in real time; DLQ empty; `clicks_dropped_total` unchanged

Screenshot: `grafana-during-run.png` (also embedded in the root README).

## Note on an earlier discarded run

The first single-worker run of this scenario produced 60 failures
(0.05%): `MaxConnectionsError` from redis-py's default 100-connection
pool cap under burst concurrency. The fix (a `BlockingConnectionPool`
so bursts queue briefly instead of erroring — see `app/main.py`) was
applied and this final run recorded. Kept here as a reminder that the
benchmark found a real bug, which is the point of running it.

## Interpretation limits

Loopback + shared hardware means these numbers demonstrate architecture
behavior (cache effectiveness, pipeline keep-up, tail shape), not
production capacity. No "scales to X" claims are made from this data.
