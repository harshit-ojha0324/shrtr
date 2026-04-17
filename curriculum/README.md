# shrtr Curriculum — learn the system you already own

This directory turns the finished shrtr service into a ~2-week learning
program. v0.1 was built AI-assisted, then audited, fixed, benchmarked, and
verified working; the goal here is that **I** can defend every design
decision in an interview and rebuild any component from a blank file.

## How to run it

1. Open a new Claude session in this repo.
2. Paste `TEACHING_PROMPT.md` as the first message (or say:
   "read curriculum/TEACHING_PROMPT.md and be my teacher").
3. Work through the stages in order, ~3–4 hours/day. Each stage ends
   with a **teach-back exam** the teacher must hold you to.

| Stage | File | What you'll own afterwards | Est. |
|---|---|---|---|
| 1 | `stage-1-hot-path-caching.md` | Cache-aside, negative caching, TTL jitter, stampedes — rebuilt from scratch | 1.5 days |
| 2 | `stage-2-rate-limiting.md` | Token bucket math, Redis Lua atomicity, fail-open/fail-closed policy | 1.5 days |
| 3 | `stage-3-streams-pipeline.md` | Redis Streams, consumer groups, PEL/XAUTOCLAIM/DLQ, effectively-once counting | 2 days |
| 4 | `stage-4-postgres-rollups.md` | Schema design, ON CONFLICT upserts, indexes, Alembic, rollup design | 1.5 days |
| 5 | `stage-5-observability-load.md` | Prometheus histograms, PromQL, Grafana, k6 — and rerunning the benchmark yourself | 1.5 days |
| 6 | `stage-6-testing-docker-interview.md` | The 3-tier test strategy, Docker/compose, CI, full interview drills | 2 days |

## The rules (what makes this hybrid mode honest)

- **Rebuild, don't reread.** For crown-jewel components the lab deletes
  the file and I rewrite it. The reference implementation is one
  `git checkout` away if I sink.
- **Teach-backs gate progress.** I answer out loud/in writing without
  looking at code. The teacher checks against the model answers and does
  NOT advance me below the pass bar.
- **Break something every stage.** I don't understand a system until
  I've watched it fail. Every stage has a break-it drill.
- **The teacher writes boilerplate, I write decisions.** Dashboard JSON
  and Dockerfiles can be generated; the Lua script, the worker's
  transaction ordering, and the cache logic I type myself.
- **Watch first, then build.** Each stage lists videos — watch the
  [core] ones before the labs, at 1.5–2x. They're chosen so the lab
  feels like applying something, not discovering it.

## Repo state assumed

Everything in this repo already works: `make test` (31 unit + component
tests), `make up` + `make itest` (6 integration tests against the real
stack), `make seed-load && make load` (k6 benchmark; see
`benchmarks/2026-07-11/`). If any of that fails, fix the environment
first — README and Makefile are the map.

## War stories to internalize (they're in this repo's history)

These came out of the pre-push audit — each is a teach-back question
somewhere in the stages:

1. **The dead NOSCRIPT branch.** The rate limiter matched `"NOSCRIPT" in
   str(exc)`, but redis-py strips that prefix — so after any Redis
   restart the reload never fired. Lesson: catch exception *types*, and
   test failure paths, not just happy paths.
2. **`--workers 2` corrupted every metric.** Two uvicorn workers, one
   `/metrics` port, per-process registries: Prometheus alternated
   between two half-counters. Lesson: know your metrics library's
   process model before you scale processes.
3. **Expired links outlived their expiry in cache.** The cache TTL
   ignored `expires_at`, so an expiring link kept redirecting up to ~25h.
   Lesson: every cache entry needs a lifetime bounded by the *data's*
   lifetime, not just the cache's.
