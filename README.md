# shrtr — Rate-Limited URL Shortener with Analytics Pipeline

A URL shortener built to be **measured**: Redis cache-aside redirect hot path, per-API-key
token-bucket rate limiting (atomic Redis Lua), asynchronous click analytics on Redis Streams
consumer groups with idempotent processing, hourly/daily rollups in PostgreSQL, and full
Prometheus/Grafana observability. One command brings up the whole stack; k6 drives load.

> **Honesty note:** this is a portfolio system, not a production service. There are no real
> users. **No performance numbers are claimed anywhere in this repo until the k6 benchmark
> protocol below has been run; the results table is intentionally empty.**

![Architecture](docs/architecture.png) <!-- to build: export from docs/architecture.md -->

```
client ──> FastAPI api ──── GET ────> Redis (cache · rate-limit buckets · "clicks" stream)
              │ cache miss                          │
              └────────> PostgreSQL <──── analytics workers (consumer group)
                          (links, rollups)           hourly/daily rollups, idempotent
Prometheus scrapes api + workers · Grafana dashboard provisioned · k6 generates load
```

## Features (MVP — implemented)
- `POST /api/v1/links` — create short link (custom alias, optional expiry), 201
- `GET /{code}` — **302** redirect hot path: cache hit = 1 Redis GET + background XADD, no DB session
- Cache-aside with **TTL jitter** (anti-stampede) and **negative caching** for unknown/inactive codes
- **Token-bucket rate limiting per API key** in a single atomic Redis **Lua** script;
  `429` + `Retry-After` + `X-RateLimit-*` headers; documented fail-open(reads)/fail-closed(writes) policy
- Click events on a **Redis Stream**; **consumer-group workers** aggregate into hourly rollups;
  daily rollup job; stats API (`?granularity=hour|day`)
- **Idempotent processing**: `processed_events` ledger; **DB commit before XACK** →
  at-least-once delivery with effectively-once counting; XAUTOCLAIM reclaim + **DLQ** for poison events
- API keys stored as **SHA-256 hashes only**; submitted URLs restricted to http/https with
  private-IP/credential/scheme-smuggling rejection
- **Prometheus** metrics (latency histograms, cache hit/miss, rate-limit decisions, stream lag,
  worker throughput, errors) + provisioned **Grafana** dashboard
- pytest at three levels: **unit** (pure logic), **component** (full pipeline in-process:
  SQLite + fakeredis-with-Lua — verifies cache-aside skips the DB, negative caching, 429 bursts,
  worker rollups, idempotent replay, DLQ), and **integration** (against the compose stack);
  k6 load script; GitHub Actions CI (lint + unit + component)

## Stretch — NOT implemented yet (labeled honestly)
- `stretch` XFetch probabilistic early cache refresh (design in docs/decisions.md)
- `stretch` Sharded click counters (write-hotspot mitigation — benchmark first, then decide)
- `stretch` Kubernetes manifests + HPA (`k8s/` contains a placeholder README only — **no K8s claim**)
- `stretch` Keyset pagination, scheduled rollup container, CI integration tests, multi-replica
  API behind a reverse proxy
- `after benchmarking` Any RPS / latency / hit-ratio number anywhere

## Quickstart (free to run: everything is local OSS containers)
Requires Docker Desktop (or Docker Engine) only.

```bash
make up          # build + start api, worker, postgres, redis, prometheus, grafana
make seed        # demo API key (printed ONCE) + 20 sample links
export KEY=<printed key>

curl -X POST localhost:8000/api/v1/links -H "X-API-Key: $KEY" \
     -H "Content-Type: application/json" -d '{"long_url":"https://example.com/long"}'
curl -i localhost:8000/<short_code>          # 302
curl "localhost:8000/api/v1/links/<short_code>/stats?granularity=hour" -H "X-API-Key: $KEY"
```

- Grafana: http://localhost:3000 (anonymous admin, dashboard "shrtr")
- Prometheus: http://localhost:9090 · API docs: http://localhost:8000/docs

```bash
make test                              # unit + component tests (no Docker needed)
SEED_API_KEY=$KEY make itest           # integration tests against the stack
make seed-load && make load            # k6: redirect hot path
docker compose up -d --scale worker=2  # two consumers in the group
make rollup                            # daily rollups + ledger purge
```

## Load test results — `after benchmarking` (pending)
| Scenario | API replicas | Target RPS | Achieved RPS | p50 | p99 | Cache hit | Err % |
|---|---|---|---|---|---|---|---|
| redirect_hot | 1 | — | _not yet run_ | — | — | — | — |
| redirect_hot | 2 | — | _not yet run_ | — | — | — | — |

**Protocol (run before filling anything in):** document hardware + Docker limits; `make seed-load`;
`make load` (Zipf-skewed codes, `redirects:0`); read p50/p95/p99 from k6 and cache hit ratio from
Grafana; commit the k6 summary JSON + screenshots to `benchmarks/<date>/`. Numbers measured on a
laptop over loopback are evidence of architecture behavior and relative scaling — **not** production capacity.

## Delivery semantics (the part interviewers ask about)
1. Worker reads a batch with `XREADGROUP` (entries enter the consumer's PEL).
2. One DB transaction: insert entry IDs into `processed_events` (`ON CONFLICT DO NOTHING RETURNING`),
   count only the *newly inserted* ones, upsert hourly rollups.
3. **Commit, then `XACK`.** A crash between the two causes redelivery; the ledger absorbs it.
4. A janitor pass `XAUTOCLAIM`s entries idle >60s from dead consumers; entries delivered >5 times
   go to `clicks:dlq`.

So: at-least-once delivery + idempotent processing = **effectively-once counting**.
("Exactly-once delivery" does not exist; this phrasing is deliberate.)

## Failure modes
| Failure | Designed behavior | Verified? |
|---|---|---|
| Redis down | redirects: cache layer raises → 500 on hit path **(known limitation: DB fallback is `to build`)**; creates fail closed (503); events drop with a counter | partially — see Limitations |
| Postgres down | cache-hit redirects keep working; creates/stats 5xx; events buffer in the stream | manual test |
| Worker killed mid-batch | unacked entries reclaimed via XAUTOCLAIM; ledger prevents double-count | integration-tested logic; chaos script `to build` |
| Poison event | parse error or >5 deliveries → DLQ + ack | unit of logic in worker; covered indirectly |
| Cache stampede | TTL jitter (MVP); XFetch `stretch` | jitter unit-tested |

## Security
SHA-256-hashed API keys (high-entropy random keys → fast hash is appropriate; bcrypt is for
low-entropy passwords) · http/https-only URLs, private/loopback/link-local IP literals rejected,
no credentials in URLs · no raw IP/User-Agent stored (UA is hashed) · ORM-parameterized queries ·
secrets via env vars. **Known gap:** DNS-rebinding (hostname → private IP) is not resolved-and-checked;
we never fetch target URLs server-side, which removes the main SSRF consequence.

## Repo map
`app/` FastAPI service (api routes, core: cache/ratelimit/events, models, schemas, observability) ·
`workers/` stream consumer + daily rollup · `migrations/` Alembic · `scripts/seed.py` ·
`tests/` unit + integration · `load/` k6 · `monitoring/` Prometheus + Grafana provisioning ·
`docker/` Dockerfile · `k8s/` stretch placeholder · `docs/` decisions & diagram

## Tradeoffs (short list; reasoning in docs/decisions.md)
302 vs 301 (keep analytics vs client caching) · events emitted *after* response (latency over
single-event durability — measured by `clicks_dropped_total`) · Redis Streams vs Kafka (zero extra
infra at this scale) · random code + unique-retry vs ID sequencer · limit/offset pagination (MVP).

## Resume claims this repo currently supports (MVP, pre-benchmark)
- Built a URL shortening service in FastAPI with PostgreSQL persistence and a Redis cache-aside
  redirect path (TTL jitter, negative caching)
- Implemented per-API-key token-bucket rate limiting with an atomic Redis Lua script
- Designed an async analytics pipeline on Redis Streams consumer groups with idempotent,
  effectively-once event counting and hourly/daily PostgreSQL rollups
- Instrumented latency histograms, cache hit ratio, and consumer lag with Prometheus/Grafana;
  containerized the stack with Docker Compose; tested with pytest and k6

## Claims that require benchmarking first
Any RPS, p50/p99 latency, cache-hit %, events/sec, "scales", "high-throughput", "low-latency",
"distributed" (also requires multi-instance verification), "fault-tolerant" (requires the chaos
tests above to be scripted and run).
