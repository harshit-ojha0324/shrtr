# Stage 6 — Testing strategy, Docker/CI, and interview drills (2 days)

The wrap-up stage: own the test pyramid, the container story, and then
defend the whole system under interview pressure.

## Why this matters

"How did you test it?" is where portfolio projects usually collapse.
This repo has an unusually defensible answer — three tiers with a
component tier that runs the FULL pipeline in-process — and you should
be able to justify every layer and its gaps.

## Watch first

- [core] **How to Use FastAPI: A Detailed Python Tutorial** — ArjanCodes — https://www.youtube.com/watch?v=SORiTsvnU28. Fills any FastAPI gaps before you defend the app structure.
- [core] **Asyncio Finally Explained: What the Event Loop Really Does** — ArjanCodes — https://www.youtube.com/watch?v=RIVcqT2OGPA. You WILL be asked why async helps here.
- [core] **Ultimate Docker Compose Tutorial** — TechWorld with Nana — https://www.youtube.com/watch?v=SXwC9fSwct8. Compose anatomy: depends_on conditions, networks, env.
- [optional] **Intro to async Python | Writing a Web Crawler** — mCoding — https://www.youtube.com/watch?v=ftmdDlwMwwQ. Await semantics from scratch.
- [optional] **import asyncio: Learn Python's AsyncIO** — EdgeDB series with Łukasz Langa (CPython core dev) — https://www.youtube.com/watch?v=Xbl7XjFYsN4 (ep. 1), https://www.youtube.com/watch?v=E7Yn5biBZ58 (ep. 2, the event loop); playlist: https://www.youtube.com/playlist?list=PLhNSoGM2ik6SIkVGXWBwerucXjgP1rHmB. Internals-level mastery, watch selectively.
- [optional] **Docker Tutorial for Beginners [FULL COURSE]** — TechWorld with Nana — https://www.youtube.com/watch?v=3c-iBn73dDE. Only if Docker itself is shaky.

## Concepts (teacher briefs these before code is shown)

1. The three tiers and what each is FOR: unit (pure logic, frozen
   clocks), component (full pipeline in one process: fakeredis-with-Lua
   + SQLite + dialect-aware upserts; SELECT-counting to prove cache
   behavior), integration (the real compose stack; PostgreSQL-specific
   behavior). What each tier can NOT catch.
2. Test honesty patterns from this repo's own audit: the vacuous
   negative-cache test (asserting two 404s proves nothing — the fix
   asserts the metric moved); the wall-clock-flaky 429 burst test (fix:
   slow the refill so elapsed time can't re-earn tokens).
3. Event-loop discipline in tests: one explicit loop shared by fixture
   setup, helpers, and loop-bound objects — why `asyncio.run()` inside
   a fixture breaks everything after it.
4. Dockerfile: multi-stage builds, non-root user, COPY + file
   permissions (this repo's 600-perms build failure), layer-cache
   economics (deps layer vs code layer — a known imperfection here;
   be able to write the better ordering).
5. Compose: healthcheck conditions (`service_healthy`,
   `service_completed_successfully`) as a dependency DAG; one-shot
   migrate services; `${VAR:-default}` for fresh-clone UX.
6. CI: lint + unit + component on every push, integration kept local
   (needs Docker) — and what you'd add next (compose-based itest job).

Reading order: `tests/` bottom-up (unit → component → integration) →
`docker/Dockerfile` → `docker-compose.yml` → `.github/workflows/ci.yml`
→ `Makefile`.

## Labs

### Lab 6.1 — Write the missing test (rebuild-solo ★)
The failure-modes table admits XAUTOCLAIM reclaim has no direct test.
Write a component test: publish events, XREADGROUP with consumer A but
do NOT ack, then have consumer B run the reclaim path (min-idle 0 for
the test) and process; assert counts are correct and nothing pending.
This closes a real, documented gap — commit it.

### Lab 6.2 — Break the build, fix the build (do-together)
Three sabotages, one at a time (teacher picks the order): a ruff
violation, a component-test regression (change negative-cache TTL logic),
and a Dockerfile COPY of a file with 600 perms. For each: what fails
FIRST (local test? CI? compose build? runtime?), and how fast would you
have caught it pre-push?

### Lab 6.3 — Fresh-clone drill (rebuild-solo ★)
In a temp directory: clone your own repo, follow README quickstart
verbatim on a machine state without `.env`. Time it. Every friction
point is a README bug — fix it upstream. (This is exactly how the
missing `pip install` step and the compose env defaults were found.)

## Interview drills (the whole repo is in scope)

**Drill A — the system walk (20 min).** "Design a URL shortener that
handles 10k redirects/sec." Design it fresh on a whiteboard, then
reconcile with what you actually built: where does the build match the
whiteboard, where does it deliberately stop short (single Redis, one
region, no CDN), and what's the upgrade path for each gap.

**Drill B — the skeptic (15 min).** Teacher attacks claims one by one:
"Your benchmark is a laptop toy." "302 doubles your traffic." "Redis is
a SPOF." "Why not just Postgres for everything at this scale?" You may
concede — knowing WHEN to concede is scored.

**Drill C — the incident (15 min).** 3am page: stats show zero clicks
for the last hour but redirects are serving fine. Debug out loud from
dashboards to root cause (teacher picks one: worker crash-loop, group
never created after a Redis flush, DB connection exhaustion, clock
skew). Ends with the postmortem paragraph.

**Drill D — resume defense (10 min).** Each resume bullet for this
project read back to you with "tell me more" three levels deep. Any
bullet you can't take three levels down gets rewritten tonight.

## Teach-back exam (no code visible)

1. ★ Defend the three-tier split. What does the component tier catch
   that unit can't, and what does integration catch that component
   can't? Give one concrete example of each from this repo.
2. ★ Why does the component suite use fakeredis-with-Lua and SQLite
   with a dialect shim instead of testcontainers? Name the trade you
   accepted (Postgres-specific behavior untested until itest).
3. ★ Explain the wall-clock flake in the original 429 test and the fix.
   What's the general rule for time in tests?
4. Walk the compose dependency DAG from `make up` to first successful
   request. Where can it still race (initdb window) and why is that
   accepted?
5. Why one uvicorn worker per container? Connect it to both the metrics
   story AND the scaling story (replicas + per-target scraping).
6. What does CI cover, what does it not, and what's the first thing
   you'd add to it? Estimate the cost of a compose-based itest job.
7. Recite your resume bullets for shrtr and, for each, the ONE number
   or artifact in the repo that backs it.
