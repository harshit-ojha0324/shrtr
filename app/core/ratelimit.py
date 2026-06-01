"""Token-bucket rate limiter, state in Redis, refill+consume atomic via Lua.

Why Lua: GET-compute-SET from app code is a check-then-act race -- two concurrent
requests can both see the last token. The script executes atomically inside Redis.
"""
import math
import time
from dataclasses import dataclass

from redis.asyncio import Redis

TOKEN_BUCKET_LUA = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill   = tonumber(ARGV[2])  -- tokens per second
local now_ms   = tonumber(ARGV[3])

local b = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(b[1])
local ts     = tonumber(b[2])
if tokens == nil then tokens = capacity end
if ts == nil then ts = now_ms end

local elapsed = math.max(0, now_ms - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * refill)

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now_ms)
-- keep state around for ~2 full refills, then let it expire
local ttl_ms = math.floor(2000 * capacity / refill)
if ttl_ms < 1000 then ttl_ms = 1000 end
redis.call('PEXPIRE', key, ttl_ms)

return {allowed, tostring(tokens)}
"""


@dataclass
class RateDecision:
    allowed: bool
    remaining: float
    capacity: int
    retry_after_s: int


class RateLimiter:
    def __init__(self, redis: Redis):
        # redis-py's Script runs EVALSHA and, on NoScriptError (Redis restart
        # flushed the script cache), reloads and retries once
        self._take = redis.register_script(TOKEN_BUCKET_LUA)

    async def take(self, key_id: int | str, capacity: int, refill_per_s: float) -> RateDecision:
        """Raises RedisError when Redis is unavailable -- caller chooses the
        fail-open / fail-closed policy (see api/deps.py)."""
        now_ms = int(time.time() * 1000)
        # guard misconfigured keys: refill <= 0 would break the Lua PEXPIRE
        # math and the retry-after division below
        refill_per_s = max(refill_per_s, 1e-6)
        args = [capacity, refill_per_s, now_ms]
        res = await self._take(keys=[f"rl:{key_id}"], args=args)
        allowed = bool(int(res[0]))
        remaining = float(res[1])
        retry_after = 0 if allowed else max(1, math.ceil((1 - remaining) / refill_per_s))
        return RateDecision(
            allowed=allowed, remaining=remaining, capacity=capacity, retry_after_s=retry_after
        )
