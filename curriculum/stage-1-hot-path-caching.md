# Stage 1 — The redirect hot path & caching (1.5 days)

The heart of the system. "Cache-aside redirect path with negative
caching and TTL jitter" is the first thing an interviewer will probe
when they see "URL shortener" on a resume.

## Why this matters

Read-heavy systems (a shortener is ~1000:1 reads:writes) live or die by
their cache strategy. Every follow-up question — invalidation,
stampedes, staleness, what happens when the cache dies — is answerable
from this one stage.

## Watch first

- [core] **Design a URL Shortener (Bitly) - System Design Interview** — NeetCodeIO — https://www.youtube.com/watch?v=qSJAvd5Mgio (~27 min). The canonical interview walkthrough; maps 1:1 onto this repo.
- [core] **Cache Systems Every Developer Should Know** — ByteByteGo — https://www.youtube.com/watch?v=dGAgxozNWFE. The mental map for the Redis layer.
- [core] **A Step-by-Step Guide for the Cache-Aside Pattern + Stampede Protection** — Milan Jovanović — https://www.youtube.com/watch?v=CVQz0E33ft4. The exact pattern pair implemented here (demo is C#; the pattern is identical).
- [optional] **Cache Stampede Problem Explained** — SystemDR — https://www.youtube.com/watch?v=TAZGA-aScPA. Stampede-only deep dive.
- [optional] **System Design: URL Shortener (with FAANG Senior Engineer)** — System Design Fight Club — https://www.youtube.com/watch?v=tm-SWO9gUAU. Second pass, different trade-off framing.
- [reading] **Design a URL Shortener Like Bitly** — Hello Interview — https://www.hellointerview.com/learn/system-design/problem-breakdowns/bitly. Staff-engineer answer key with the read/write-ratio math.
- [reading] **Top caching strategies** — ByteByteGo blog — https://blog.bytebytego.com/p/top-caching-strategies. Cache-aside vs read-through vs write-through/back flashcard.

## Concepts (teacher briefs these before code is shown)

1. Cache-aside vs read-through/write-through — who owns the fill, and
   why cache-aside fits a read-heavy redirect (miss = point read + fill).
2. Negative caching: why "this code does not exist" must ALSO be cached
   (typo/scanner traffic would otherwise always hit PostgreSQL).
3. TTL jitter: why a fleet of keys created together expires together,
   and what that does to the database at second N.
4. Cache invalidation on create/delete — and why the delete path here
   writes a tombstone (`set_negative`) rather than only deleting.
5. Data-bounded TTLs: the cache entry's lifetime must be clamped to the
   *link's* remaining lifetime (`expires_at`), not just the cache policy.
   (This repo shipped that bug and fixed it — see decisions.md.)
6. 302 vs 301, and `Cache-Control` as a load-shedding dial.
7. Why click events are emitted AFTER the response (BackgroundTasks) and
   what that trades away.

Reading order: `app/core/cache.py` → `app/api/routes_redirect.py` →
`app/core/events.py` → ADR-1/ADR-2 in `docs/decisions.md`.

## Labs

### Lab 1.1 — Rebuild the cache layer (rebuild-solo ★)
Move `app/core/cache.py` aside and rewrite it from this spec:
positive key `link:{code}` with TTL = base + uniform jitter, clamped to
the link's remaining lifetime when `expires_at` is passed (skip caching
entirely if <2s remain); negative key `404:{code}` with a short fixed
TTL; `invalidate()` drops both keys. Grade: `make test` — the cache and
pipeline tests must pass unmodified.

### Lab 1.2 — Rebuild the redirect handler (rebuild-solo ★)
Move `app/api/routes_redirect.py` aside; rewrite from the docstring
spec. Requirements you must rediscover: validate the code format
in-handler (404, never 422), check negative cache only after a positive
miss, exactly one DB point-read per miss, `set_negative` on miss/inactive,
emit the click via BackgroundTasks after the response. Grade:
`make test` (component tests count SELECTs to prove hits skip the DB).

### Lab 1.3 — Trace four requests (do-together)
On paper, no code: (a) hot code, cache hit; (b) first-ever request for a
fresh code; (c) request for a deleted link 10s after deletion; (d)
request for a link that expired 5 minutes ago but was cached yesterday.
Then verify each against the code. (d) is the war-story question.

### Lab 1.4 — The stampede experiment (do-together)
`make up`, seed, then: set `cache_jitter_seconds=0`, warm 1000 keys in a
loop, wait for simultaneous expiry while running `make load`, and watch
the DB-select rate spike in Grafana. Restore jitter, repeat, compare.

## Break-it drill

`docker stop shrtr-redis-1` mid-load. Predict FIRST, in writing: what
happens to (a) cache-hit redirects, (b) cache-miss redirects, (c) link
creates, (d) click events? Then run it, check `clicks_dropped_total` and
the error panels, and reconcile every wrong prediction. Bring Redis back
and watch recovery.

## Teach-back exam (no code visible)

1. ★ Walk through a cache miss end-to-end: every Redis command, every
   SQL statement, in order.
2. ★ Why negative caching? What attack/traffic pattern does it absorb,
   and what new staleness problem does it create for just-created links?
3. ★ Why is the TTL clamped to `expires_at`, and what happened before it
   was? (The ~25h stale-redirect bug — explain the mechanism.)
4. What is a cache stampede, what does TTL jitter do about it, and what
   is XFetch (ADR-7) — why is it better than jitter alone?
5. Why 302 and not 301? What does `Cache-Control: private, max-age=90`
   trade against analytics accuracy?
6. A click event is lost. Name the exact window in which the crash must
   have happened, and the metric that makes the loss visible.
7. The delete handler writes a tombstone AND deletes the positive entry.
   What ordering bug can still re-cache a deleted link? (Known
   limitation — you must be able to explain the race, not just cite it.)

Model answers live in the code and docs/decisions.md; the teacher grades
against them.
