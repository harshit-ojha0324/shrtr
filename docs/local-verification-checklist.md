# Local Verification Checklist

The repo's logic was verified in a sandbox with in-process tests (31 passing), but the
**Docker Compose stack itself has never been run** — no Docker was available there. This
checklist is your first true full-stack run. Work top to bottom; each step lists the command,
what you should see, what failure usually means, and what resume evidence the step produces.

Keep a terminal log (`script verification.log` on macOS/Linux) — it's your proof trail.

---

## 0. Prerequisites

**Command:** `docker --version && docker compose version`
**Expect:** versions print (Docker ≥ 24, Compose v2). Docker Desktop must be running.
**Failure means:** Docker not installed/running → install Docker Desktop, retry.
**Evidence:** none (prerequisite).

**Command:** `cp .env.example .env`
**Expect:** silent success. Compose injects its own env, so this matters only for non-Docker runs and for setting `SEED_API_KEY` later.
**Failure means:** wrong directory — run from the `shrtr/` repo root.
**Evidence:** none.

## 1. Bring the stack up

**Command:** `make up`
**Expect:** image builds (~1–3 min first time); then `docker compose ps` shows postgres, redis, api, worker, prometheus, grafana `Up`, with postgres/redis/api `(healthy)`; `migrate` shows `Exited (0)` — that's correct, it's a one-shot job.
**Failure means:** port conflict (something on 5432/6379/8000/9090/3000 — stop it or edit ports in compose); build error (read the line — likely a dependency pin); `migrate` exited non-zero → `docker compose logs migrate` (Alembic error).
**Evidence:** screenshot of `docker compose ps` all-healthy → supports "containerized multi-service deployment with Docker Compose."

**Command:** `docker compose ps && docker compose logs --tail=20 api worker`
**Expect:** api logs show Uvicorn startup; worker logs show `worker worker-<pid> consuming clicks/analytics`.
**Failure means:** worker crash-loop → usually Redis/Postgres not ready or a connection-string issue; read the traceback.
**Evidence:** worker log line → supports "consumer-group worker" claim.

## 2. Seed and exercise the API

**Command:** `make seed`
**Expect:** `wrote 20 codes to .../load/codes.json`, then `=== DEMO API KEY ===` with the key printed once. Save it: `export KEY=<that value>`.
**Failure means:** migrate didn't run (tables missing) → `make migrate` then retry.
**Evidence:** none directly; enables everything below.

**Command (create):**
```bash
curl -s -X POST localhost:8000/api/v1/links -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" -d '{"long_url":"https://example.com/proof"}'
```
**Expect:** JSON with `short_code`, `short_url`; HTTP 201. Save the code: `export CODE=<short_code>`.
**Failure means:** 401 → wrong key; 503 → Redis down (rate limiter fail-closed on writes — check `docker compose ps redis`); connection refused → api not up.
**Evidence:** supports "REST API with FastAPI + PostgreSQL persistence." For the persistence claim specifically, also run:
`docker compose exec postgres psql -U shrtr -c "SELECT short_code,long_url FROM links ORDER BY id DESC LIMIT 3;"`
**Expect:** your row is there. That's PostgreSQL persistence verified end-to-end.

**Command (redirect, twice):** `curl -si localhost:8000/$CODE | head -5` (run it twice)
**Expect:** `HTTP/1.1 302 Found`, `location: https://example.com/proof`, `cache-control: private, max-age=90` both times. First call is a cache miss (fills Redis), second is a hit.
**Failure means:** 404 → wrong CODE; 500 → check Redis is healthy (known limitation: Redis fully down breaks the hot path).
**Evidence:** supports "302 redirect hot path." To prove the cache-aside part at the Redis level:
`docker compose exec redis redis-cli GET "link:$CODE"`
**Expect:** your long URL. `TTL "link:$CODE"` should show ~86400–90000s (base TTL + jitter — jitter evidence!).

**Command (negative cache):** `curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/nope9999` then `docker compose exec redis redis-cli GET "404:nope9999"`
**Expect:** `404`, then `"1"`.
**Evidence:** negative caching claim.

**Command (rate limit):**
```bash
for i in $(seq 1 70); do curl -s -o /dev/null -w "%{http_code} " -H "X-API-Key: $KEY" "localhost:8000/api/v1/links?limit=1"; done; echo
```
**Expect:** a run of `200`s (~60, the bucket capacity) then `429`s. Check headers on a 429: `curl -si -H "X-API-Key: $KEY" "localhost:8000/api/v1/links?limit=1" | grep -i -E "retry-after|ratelimit"`.
**Failure means:** all 200s → you waited between runs (refill 1/s) — run the loop faster or twice.
**Evidence:** screenshot of the 200→429 flip + headers → supports "token-bucket rate limiting per API key (Redis Lua)."

## 3. Verify the analytics pipeline

**Command (stream):** `docker compose exec redis redis-cli XLEN clicks`
**Expect:** ≥ the number of redirects you made. Note: the worker consumes constantly, so also check the group exists: `docker compose exec redis redis-cli XINFO GROUPS clicks` (shows `analytics`, consumers ≥1).
**Failure means:** 0 and never rises → events not publishing; check api logs and `clicks_dropped_total` in /metrics.
**Evidence:** supports "click events published to Redis Streams."

**Command (rollups):** click your link a few more times, wait ~5s, then:
```bash
docker compose exec postgres psql -U shrtr -c "SELECT * FROM click_rollups_hourly ORDER BY bucket_start DESC LIMIT 5;"
curl -s -H "X-API-Key: $KEY" "localhost:8000/api/v1/links/$CODE/stats?granularity=hour"
```
**Expect:** rows with your link_id and a clicks count matching your redirects; stats JSON agrees.
**Failure means:** empty → worker not consuming (logs!), or you queried before the batch flushed (XREADGROUP blocks 5s — wait and retry).
**Evidence:** THE pipeline claim: "consumer groups aggregating into hourly PostgreSQL rollups." Also check the ledger: `SELECT count(*) FROM processed_events;` ≈ total clicks (idempotency ledger working).

**Command (daily rollup):** `make rollup`
**Expect:** `daily rollup: upserted N day-buckets, purged 0 ledger rows`.
**Evidence:** "hourly/daily rollups."

**Optional but high-value (worker kill test):** start load (step 5), then `docker compose kill worker && sleep 70 && docker compose up -d worker`, then compare `XLEN`/`XPENDING` and final counts vs. clicks sent.
**Expect:** pending entries get reclaimed (XAUTOCLAIM after 60s idle), counts converge with no double-counting.
**Evidence:** this is your honest "tested worker-crash recovery" line — and a great interview story. Save the terminal output to `benchmarks/<date>/chaos-worker-kill.txt`.

## 4. Observability

**Command:** `curl -s localhost:8000/metrics | grep -E "^(http_request_duration_seconds_count|cache_ops_total|rate_limit_decisions_total|clicks_published_total)" | head`
**Expect:** series with nonzero values; `cache_ops_total{result="hit"}` > 0 after your second redirect.
**Evidence:** "Prometheus metrics" claim.

**Command:** open http://localhost:9090/targets
**Expect:** `shrtr-api` and `shrtr-worker` both UP.
**Failure means:** worker target down → worker container not running or port 9100 metric server failed (logs).

**Command:** open http://localhost:3000 → dashboard "shrtr"
**Expect:** panels populate (RPS, latency quantiles, cache hit ratio, 429s, consumer lag, events).
**Failure means:** blank panels → no traffic yet (run step 5), or provisioning path issue (`docker compose logs grafana`).
**Evidence:** screenshot under load → README + "Grafana dashboards" claim.

## 5. Tests and load

**Command:** `pip install -e ".[dev]" && make test`
**Expect:** `31 passed` (unit + component; no Docker needed).
**Evidence:** "three-tier pytest suite" claim; CI badge will mirror this.

**Command:** `SEED_API_KEY=$KEY make itest` (note: itest reads SEED_API_KEY and BASE_URL; stack must be up)
**Expect:** all integration tests pass, including the rollup round-trip within 15s and the 429 burst.
**Failure means:** rollup timeout → worker not consuming; rate-limit test flaky if you just burned the bucket — wait 60s, rerun.
**Evidence:** strongest pre-benchmark proof: real Postgres + real Redis + real worker, end to end.

**Command:** `make seed-load` then `make load`
**Expect:** seed writes 10k codes to load/codes.json; k6 ramps to ~500 req/s for 3 min and prints a summary (`http_req_duration` p95/p99, checks % of 302s). On Linux, if `host.docker.internal` fails, add `--add-host=host.docker.internal:host-gateway` to the docker run line in the Makefile.
**Failure means:** mass `connection refused` → BASE_URL wrong; many non-302 checks → codes.json stale (reseed); k6 maxVUs warnings → raise `preAllocatedVUs`.
**Evidence:** **this is the gate for every number.** Only after this run can you fill the README results table.

## 6. Recording benchmark output

- Create `benchmarks/<YYYY-MM-DD>/` and save: the full k6 terminal summary (or rerun with `--summary-export benchmarks/<date>/summary.json`), a `notes.md` with your hardware (CPU model, cores, RAM), Docker resource limits, replica counts, and exact command; Grafana screenshots taken DURING the run; the `docker compose ps` screenshot; chaos-test output if done.
- Fill the README "Load test results" table only from these files. State conditions next to every number.
- Commit the folder. Numbers without committed evidence don't go on the resume.

## 7. Screenshots to capture (README + interview deck)

1. `docker compose ps` all healthy
2. Grafana full dashboard mid-load (the money shot)
3. Grafana latency panel close-up (p50/p95/p99 visible)
4. Cache hit ratio panel after warmup
5. 429 panel during the rate-limit burst
6. k6 terminal summary
7. psql rollup rows + matching stats API response side by side
8. Prometheus /targets page (both UP)

When all steps pass, you may move your resume from Version A to **Version B** bullets
(see docs/resume-backend-rewrite.md). Version C requires step 6 evidence.
