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
- Daily rollup is manual (`make rollup`); scheduling is `stretch`.
- In-process API-key cache (60s TTL) means a revoked key works up to 60s per API replica.
- Chaos tests are described but not yet scripted (`to build`).
