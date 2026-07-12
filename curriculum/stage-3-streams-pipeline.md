# Stage 3 — The analytics pipeline: Redis Streams + idempotency (2 days)

The crown jewel. "Effectively-once counting on at-least-once delivery"
is the sentence that separates you from candidates who say
"exactly-once" and get dismantled.

## Why this matters

Every event-pipeline interview converges on the same three questions:
what happens when the consumer crashes mid-batch, how do you avoid
double-counting, and what do you do with poison messages. This stage
makes all three reflexive — with Redis Streams vocabulary that
transfers 1:1 to Kafka (PEL ≈ unacked offsets, XAUTOCLAIM ≈ rebalance,
DLQ is DLQ).

## Watch first

- [core] **Redis Streams Explained** — Redis (official) — https://www.youtube.com/watch?v=Z8qcpXyMAiA. Streams, consumer groups, acks in one short pass.
- [core] **Apache Kafka® Transactions: Message Delivery and Exactly-Once Semantics** — Confluent — https://www.youtube.com/watch?v=Ki2D2o9aVl8. The authoritative "exactly-once is really at-least-once + idempotency" explanation.
- [optional] **Introducing Redis Streams with RedisInsight, Node.js and Python** — Redis (official) — https://www.youtube.com/watch?v=q2UOkQmIo9Q. Hands-on, mirrors the consumer code here.
- [optional] **Using Redis Streams instead of Kafka** — Interview Pen — https://www.youtube.com/watch?v=zcCEFByssQU. Directly answers "why not Kafka?" (ADR-3).
- [optional] **Kafka Delivery Semantics** — Code with Irtiza — https://www.youtube.com/watch?v=V0c0qAP7sWk. Quick visual of the three guarantees.
- [reading] **Redis Streams intro** — redis.io — https://redis.io/docs/latest/develop/data-types/streams/ — treat as REQUIRED. XADD, XREADGROUP, PEL, XACK, XAUTOCLAIM end-to-end.
- [reading] **At most once, at least once, exactly once** — ByteByteGo blog — https://blog.bytebytego.com/p/at-most-once-at-least-once-exactly. Interview flashcard.

## Concepts (teacher briefs these before code is shown)

1. Streams vs Pub/Sub vs lists: persistence, consumer groups, fan-out.
2. The PEL (pending entries list): what "delivered but not acked" means
   physically, and how `XREADGROUP ... >` differs from re-reading `0`.
3. Why "exactly-once delivery" is impossible (two generals), and what
   "at-least-once delivery + idempotent processing = effectively-once
   counting" actually commits you to.
4. The idempotency ledger: `INSERT ... ON CONFLICT DO NOTHING RETURNING`
   as a set-membership test *inside the same transaction as the effect*.
5. Commit-before-XACK ordering: enumerate the crash windows on both
   orderings and show why commit-first is the one the ledger can absorb.
6. XAUTOCLAIM: reclaiming from dead consumers, min-idle, delivery
   counts, and the poison-event DLQ path (bounded via MAXLEN).
7. Rollups: hourly upsert with `clicks = clicks + EXCLUDED.clicks`,
   daily aggregation, and the ledger purge (why 48h, what replay after
   purge would mean — known limitation).
8. Backpressure & loss: `stream_maxlen` as a bounded-loss backstop,
   `clicks_dropped_total` for producer-side drops.

Reading order: `app/core/events.py` → `workers/analytics.py` (top
docstring, then `process_batch`, then `reclaim_stalled`) →
`workers/rollup_daily.py` → ADR-2/3/4 in `docs/decisions.md`.

## Labs

### Lab 3.1 — Rebuild `process_batch` (rebuild-solo ★)
Move `workers/analytics.py` aside; rewrite `process_batch` from this
spec: parse entries (malformed → DLQ + ack); one DB transaction that
(a) bulk-inserts entry IDs into the ledger with ON CONFLICT DO NOTHING
RETURNING, (b) counts only newly-inserted IDs into hourly buckets keyed
by (link_id, hour_floor), (c) upserts rollups additively; XACK only
after commit; metrics for processed/duplicate/skipped. Grade:
`make test` — the idempotent-replay component test must pass unmodified.

### Lab 3.2 — Crash-window tracing (do-together)
On paper: the worker dies (1) after XREADGROUP but before the DB
transaction, (2) after commit but before XACK, (3) mid-transaction.
For each: where does the entry live (stream? PEL? ledger?), who picks
it up, and what does the final count say? Then kill the real worker
(`docker kill shrtr-worker-1`) at load and watch XAUTOCLAIM + the
ledger do their jobs.

### Lab 3.3 — Poison and the DLQ (do-together)
`XADD clicks '*' garbage nothing` via redis-cli, plus an event whose
delivery count you drive past `worker_max_deliveries` (stop the worker
mid-PEL repeatedly). Verify both land in `clicks:dlq` with reason
fields, and pending returns to 0.

### Lab 3.4 — Consumer group scaling (do-together)
`docker compose up -d --scale worker=2`, drive load, and prove entries
are split (XINFO GROUPS / consumer stats) with no double-counting
(stats total equals k6 request count). Note the observability
limitation: only one worker's metrics are scraped (static target).

## Break-it drill

Combined: under `make load`, kill the worker mid-run, wait 90s, start
it again, and reconcile: published events vs processed vs stats API
total vs k6's request count. Every number must be explainable —
"roughly equal" is a fail; know where each delta comes from
(background-task drops? trim? pending?).

## Teach-back exam (no code visible)

1. ★ "Does this system count clicks exactly once?" — the full correct
   answer, including why the phrase "exactly-once delivery" is a trap.
2. ★ Walk the commit-before-XACK crash window and how the ledger
   absorbs the redelivery. Then flip the order and name the bug.
3. ★ What is the PEL? An entry has been in it for 10 minutes — walk
   the XAUTOCLAIM path including the delivery-count check and DLQ.
4. Why ON CONFLICT DO NOTHING **RETURNING**? What breaks if you count
   all batch entries instead of only the returned ones?
5. Why Redis Streams and not Kafka here? Name the scale/requirements
   line where that answer flips.
6. A click event is published but never processed, and no error was
   logged anywhere. Name two distinct mechanisms that could cause this
   (trim backstop; drop-after-response) and the metric for each.
7. The ledger is purged after 48h. Construct the (unlikely) replay
   scenario that would double-count, and say why it's accepted.
