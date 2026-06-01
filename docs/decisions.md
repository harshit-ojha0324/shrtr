# Architecture Decision Records (short form)

## ADR-1: 302 instead of 301
301 is cached aggressively by browsers/CDNs; repeat visitors would bypass us entirely and
analytics would undercount. 302 + `Cache-Control: private, max-age=90` keeps us in the path
while bounding repeat-click load. Tradeoff accepted: more traffic terminates at our service.

## ADR-2: emit click events AFTER the response (BackgroundTasks)
Keeps analytics out of the hot-path latency budget. Cost: a process crash between response and
XADD loses that one click (observable via `clicks_dropped_total`/restart counts). Acceptable for
analytics; for billing-grade events we would emit before responding and accept the latency.

## ADR-3: Redis Streams, not Kafka
One consumer group, modest event rates, Redis already deployed for cache + rate limiting →
Streams adds zero infrastructure. Kafka becomes right at multi-service fan-out, long retention,
or replay-at-scale requirements. `XTRIM MAXLEN ~1M` makes the bounded-retention tradeoff explicit.

## ADR-4: idempotency ledger (`processed_events`) + commit-before-XACK
Exactly-once *delivery* is impossible; we implement at-least-once delivery with idempotent
processing. The ledger insert and the rollup upsert share one transaction, so a redelivered
entry can never be counted twice. Ledger is purged after 48h (stream IDs older than the trimmed
stream cannot be redelivered).

## ADR-5: random 7-char base62 codes + unique-index retry
62^7 ≈ 3.5×10^12 keyspace → collisions negligible; retry loop handles them correctly anyway.
Avoids a coordination point (sequencer) and non-enumerable codes are a privacy win. At true
Bitly scale, a pre-generated key service would be the answer.

## ADR-6: rate-limiter failure policy
Redis down → reads fail OPEN (availability; they're cheap), writes fail CLOSED (protect
Postgres). Chosen consciously; visible in api/deps.py and monitored via metrics.

## ADR-7 (stretch, not built): XFetch early refresh
TTL jitter handles batch de-synchronization. XFetch (Vattani et al., VLDB 2015) would refresh
hot keys early with probability rising near expiry: refresh if
`now - delta * beta * ln(rand()) >= expiry`. Planned as a stretch with a before/after stampede demo.

## Known limitations (honest list)
- Redis fully down currently breaks the redirect hot path (DB-direct fallback is `to build`).
- DNS rebinding not checked in URL validation (we never server-side fetch targets, which is the
  main mitigation).
- limit/offset pagination; keyset is `stretch`.
- Daily rollup + ledger purge run hourly from a `sleep 3600` loop in the `rollup` compose
  service (a K8s CronJob would replace it). Its fixed 2-day window means a >2-day gap in
  running it leaves days that only appear in hourly rollups. Hourly rollups are never pruned
  (one row per link per active hour; small next to the per-click ledger it now purges).
- In-process API-key cache (60s TTL) means a revoked key works up to 60s per API replica.
- Chaos tests are described but not yet scripted (`to build`).
- Cache-aside write/invalidate races: a redirect miss that overlaps a DELETE can still re-fill
  the positive cache after the delete, but it can no longer redirect: the redirect reads both
  keys in one MGET and the negative entry wins, and DELETE writes a tombstone that outlives any
  positive TTL (base + jitter). Still open: a miss that overlaps a create can leave a negative
  entry for up to 5 minutes (new link 404s briefly); accepted at this scale.
- The rate limiter trusts the app server's wall clock (`now_ms` argument). Multi-node skew
  could mint tokens; single-writer Redis TIME inside the Lua script would remove that.
- `stream_maxlen` trimming is a backstop: if consumers are down long enough for 1M events to
  accumulate, the oldest untrimmed-but-never-delivered clicks are silently lost (bounded loss,
  chosen over unbounded Redis growth).
- Prometheus scrapes a single static `worker:9100` target; `--scale worker=2` runs correctly
  (consumer group) but only one worker's metrics are collected without DNS-SD (`stretch`).

## Fixed after self-audit (July 2026)
A multi-pass audit before the first public push found and fixed, among smaller items:
- **Rate-limiter NOSCRIPT recovery was dead code** — redis-py strips the `NOSCRIPT` prefix
  from the exception message, so the string-match reload branch never fired; after any Redis
  restart, writes would 503 forever. Now catches `NoScriptError` (verified with a live
  restart drill).
- **`uvicorn --workers 2` silently corrupted every API metric** — `prometheus_client`
  registries are per-process, so `/metrics` alternated between two half-counters. One worker
  per container now; scale with replicas.
- **Expired links kept redirecting from cache** for up to ~25h past `expires_at`; the cache
  TTL is now clamped to the link's remaining lifetime.
- **Prometheus label-cardinality leak** — unmatched request paths were used verbatim as the
  `route` label (every scanner probe minted a new series); now bucketed as `unmatched`.
- **Alternate IPv4 spellings bypassed the private-IP block** (decimal `2130706433`, octal,
  hex, short forms); the validator now normalizes them via `inet_aton` before checking.
- Malformed short codes (e.g. `/favicon.ico`) returned 422 with pydantic internals instead
  of a plain 404; naive/past `expires_at` values were accepted silently; the DLQ stream was
  unbounded; the k6 Zipf sampler could never pick the hottest code (off-by-one).
