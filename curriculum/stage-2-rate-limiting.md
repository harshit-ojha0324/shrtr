# Stage 2 — Rate limiting with Redis Lua (1.5 days)

The most interview-dense 100 lines in the repo. "Design a rate limiter"
is a standard system-design question, and this stage means you've
actually built the answer.

## Why this matters

Token bucket + atomicity + failure policy covers three interview layers
at once: the algorithm, the distributed-correctness trap
(check-then-act races), and the operational judgment call
(fail open vs fail closed). Most candidates can only recite the first.

## Watch first

- [core] **Rate Limiter System Design: Token Bucket, Leaky Bucket, Scaling** — ByteByteGo — https://www.youtube.com/watch?v=YXkOdWBwqaA. Alex Xu's own treatment of the classic chapter.
- [core] **System Design Interview - Rate Limiting (local and distributed)** — System Design Interview (Mikhail Smarshchok) — https://www.youtube.com/watch?v=FU4WlwfS3G0. The deepest free treatment; includes the exact race the Lua script kills.
- [optional] **Rate Limiting system design | TOKEN BUCKET, Leaky Bucket, Sliding Logs** — Tech Dummies — https://www.youtube.com/watch?v=mhUQe4BKZXs. Slower walkthrough of each algorithm.

## Concepts (teacher briefs these before code is shown)

1. Token bucket vs leaky bucket vs fixed/sliding window — what burst
   behavior each allows and why bucket-with-burst fits an API.
2. The check-then-act race: why GET → compute → SET from app code lets
   two concurrent requests both spend the last token, and the three
   fixes (Lua script, WATCH/MULTI, single-writer).
3. Lazy refill: tokens computed from elapsed time on each request —
   no background refill job. Where the clock lives and why that's a
   *documented limitation* here (app server clock, multi-node skew).
4. `retry_after = ceil((cost - tokens) / refill_rate)` — derive it.
5. EVALSHA vs EVAL, the script cache, and the NOSCRIPT war story: the
   old code string-matched `"NOSCRIPT" in str(exc)` but redis-py strips
   that prefix — the recovery branch was dead code. Why catching
   `NoScriptError` (a type) is the correct fix, and why the final code
   just uses `redis.register_script` (read its `__call__`: it is that fix).
6. Failure policy: reads fail OPEN, writes fail CLOSED (ADR-6). Why the
   asymmetry, and what "protect PostgreSQL" concretely means.
7. Bucket-state TTL: why the Lua script PEXPIREs the hash, and what a
   zero/negative refill rate would do to that math.

Reading order: `app/core/ratelimit.py` (Lua first, then `take`) → `app/api/deps.py` → `tests/unit/test_token_bucket_math.py`.

## Labs

### Lab 2.1 — Rebuild the token bucket (rebuild-solo ★)
Move `app/core/ratelimit.py` aside; rewrite from this spec: Redis hash
`rl:{key_id}` holding `tokens` and `ts`; a Lua script that refills
lazily (`min(capacity, tokens + elapsed_s * refill)`), spends `cost` if
available, PEXPIREs the state to ~2 full refills, and returns
`{allowed, tokens}`; EVALSHA with a `NoScriptError` reload (hand-roll it
once, then swap in `register_script`); `Retry-After` computed with a real
ceiling.
Grade: `make test` — the frozen-clock unit tests (real Lua via fakeredis,
clock frozen by patching `ratelimit.time`) must pass unmodified.

### Lab 2.2 — Race demonstration (do-together)
Write a throwaway script that implements the limiter the WRONG way
(GET/compute/SET from Python) and hammer it with 50 concurrent tasks on
a bucket of capacity 10. Count how many requests were allowed. Repeat
against the Lua version. The delta is your interview anecdote.

### Lab 2.3 — The failure-policy walk (do-together)
On paper: Redis is down. For each of (a) GET /api/v1/links,
(b) POST /api/v1/links, (c) GET /{code} cache hit, (d) GET /{code}
cache miss — what status does the client see and WHY is that the right
call? Verify against `deps.py` and the failure-modes table, then run
the break-it drill to confirm.

## Break-it drill

`docker restart shrtr-redis-1` while hitting the API in a loop with a
valid key. Watch for: any 500s? Do `X-RateLimit-Remaining` headers
resume correctly (fresh bucket)? This drill is exactly how the dead
NOSCRIPT branch was proven fixed — reproduce that verification.
Then: `docker stop shrtr-redis-1` (fully down, not restarting) and
confirm reads still 200 (fail open) while creates 503 (fail closed).

## Teach-back exam (no code visible)

1. ★ Write the refill formula from memory and explain why there is no
   background refill job.
2. ★ Two requests arrive in the same millisecond with 1 token left.
   Walk through exactly why app-side check-then-act double-spends and
   why the Lua script cannot.
3. ★ Redis restarts. Walk the full recovery path of the next request:
   what exception, what reload, what the client sees. Why did the old
   string-match version fail silently?
4. Why do reads fail open but writes fail closed? Give one scenario
   where each choice saves you and one where it hurts.
5. Derive the Retry-After value for: capacity 60, refill 1/s, bucket
   empty, cost 1. Why ceil and not round?
6. What does the PEXPIRE in the script protect against? What would
   `refill_per_s = 0` have done before the guard?
7. This limiter is per-API-key on one Redis. What changes at 10 Redis
   shards? At two app regions with clock skew? (Known limitation —
   explain the mechanism, then the single-writer TIME fix.)
