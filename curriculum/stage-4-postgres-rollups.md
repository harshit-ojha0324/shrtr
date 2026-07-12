# Stage 4 — PostgreSQL: schema, upserts, indexes, migrations (1.5 days)

The persistence layer. Less flashy than streams, but index questions
and "how would you page this table" kill more candidates than
consensus algorithms ever will.

## Why this matters

The schema here is small enough to hold in your head and real enough
to defend: a unique hot-path index, additive rollup upserts, a ledger
table with TTL semantics, and Alembic migrations wired into compose.

## Watch first

- [core] **Database Indexing Explained (with PostgreSQL)** — Hussein Nasser — https://www.youtube.com/watch?v=-qNSXK7s7_w. Page I/O, B-trees, why the short_code unique index IS the hot path.
- [core] **Alembic Introduction - Migrations and Auto-Generating Revisions** — BugBytes — https://www.youtube.com/watch?v=i9RX03zFDHU. The autogenerate workflow used here.
- [core] **SQLAlchemy 2.0 - The One-Point-Four-Ening** (Mike Bayer, SQLAlchemy's creator) — Six Feet Up — https://www.youtube.com/watch?v=1Va493SMTcY. Why the 2.0 select() style + async support look the way they do.
- [optional] **PostgreSQL Upsert Using INSERT ON CONFLICT** — Sql With Prashant — https://www.youtube.com/watch?v=CT6OXBzw3Vw. Hands-on ON CONFLICT DO UPDATE demo.
- [reading] **PostgreSQL UPSERT** — Neon tutorial — https://neon.com/postgresql/postgresql-tutorial/postgresql-upsert. Conflict targets, DO NOTHING vs DO UPDATE, the EXCLUDED pseudo-table.
- [reading] **Asynchronous SQLAlchemy 2 step-by-step** — DEV Community — https://dev.to/amverum/asynchronous-sqlalchemy-2-a-simple-step-by-step-guide-to-configuration-models-relationships-and-3ob3. The async engine + async Alembic env.py setup videos usually skip.

## Concepts (teacher briefs these before code is shown)

1. The schema as a whole: `links`, `api_keys`, `click_rollups_hourly`,
   `click_rollups_daily`, `processed_events` — and which query each
   index serves. Nothing exists without a query that needs it.
2. Upsert mechanics: conflict target = unique index; `EXCLUDED` as "the
   row that failed to insert"; additive update
   (`clicks = clicks + EXCLUDED.clicks`) vs overwrite.
3. Why rollups at all: raw click events vs pre-aggregation; the
   read-amplification math for a stats query over 30 days.
4. Random short codes + unique-index-retry (ADR-5) vs sequencers vs
   pre-generated key services. Collision probability at 62^7.
5. The dialect-aware upsert shim (`app/db/upsert.py`) that lets SQLite
   component tests exercise the same code path as PostgreSQL.
6. Alembic: env.py wiring (async engine, DATABASE_URL from env,
   fileConfig logging), the migrate one-shot compose service, and
   `service_completed_successfully` ordering.
7. asyncpg + timestamptz: why naive datetimes are a data-corruption
   hazard (the expires_at validator war story).
8. limit/offset pagination and its O(offset) cost; keyset as the fix
   (stretch — be able to write the WHERE clause).

Reading order: `migrations/versions/0001_initial.py` →
`app/models/*.py` → `app/db/upsert.py` → `workers/rollup_daily.py` →
`app/api/routes_links.py` (stats query).

## Labs

### Lab 4.1 — Explain every index (do-together)
For each index in `0001_initial.py`: name the exact query in the code
that uses it, and predict the plan. Then verify with
`EXPLAIN ANALYZE` inside `docker exec -it shrtr-postgres-1 psql`.
Any index with no query is a finding; any hot query with no index is
a bigger one.

### Lab 4.2 — Rebuild the rollup upsert (rebuild-solo ★)
Move `workers/rollup_daily.py` aside and rewrite it: aggregate hourly
rows into daily buckets with an additive ON CONFLICT upsert, then purge
ledger entries older than 48h. State in a comment why purge-after-48h
is safe *enough* (stream trim horizon) and what replay after purge
would do.

### Lab 4.3 — Keyset pagination (do-together, stretch)
Implement `GET /api/v1/links?after=<created_at,id>` keyset pagination
alongside the offset version. Measure both at offset 9,000 with
EXPLAIN ANALYZE on the seeded 10k rows. Keep it on a branch — it's a
documented stretch, and the diff is your talking point.

## Break-it drill

`docker stop shrtr-postgres-1` under load. Predict first: cache-hit
redirects? cache-miss redirects? creates? stats? worker batches (they
should fail, NOT ack, and redeliver later — verify pending grows and
then drains after restart). Bring it back; verify counts reconcile —
the pipeline should have lost nothing while the DB was down.

## Teach-back exam (no code visible)

1. ★ Write the rollup upsert SQL from memory, including the conflict
   target and the EXCLUDED arithmetic.
2. ★ Why is the `processed_events` insert in the SAME transaction as
   the rollup update? What breaks if it's a separate transaction?
3. ★ A stats query for 30 days at hourly granularity: how many rows
   does it scan with rollups vs without? Why is the PK
   (link_id, bucket_start) the right shape — and why does bucket_start
   come second?
4. Postgres was down for 10 minutes under load. Explain why zero clicks
   were lost (walk: stream buffering → PEL → failed batch not acked →
   redelivery), and which part of that you'd demo in Grafana.
5. Why random codes with retry instead of an auto-increment sequencer?
   Name the two things the sequencer costs you.
6. What does the SQLite-vs-Postgres upsert shim buy the test suite,
   and what PostgreSQL-specific behavior do component tests therefore
   NOT cover (name where that gap is covered instead)?
7. Why must `expires_at` reject naive datetimes? Walk the IST-user
   scenario end to end.
