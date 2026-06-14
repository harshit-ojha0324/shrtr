"""Analytics consumer worker (Redis Streams consumer group).

Guarantees:
- at-least-once delivery (Redis PEL + XAUTOCLAIM reclaim of stalled entries)
- idempotent processing via the processed_events ledger
- DB transaction COMMITS BEFORE XACK -> crash between the two causes a
  redelivery that the ledger absorbs (effectively-once counting)
- poison events: parse failures and entries delivered > MAX_DELIVERIES go to
  the DLQ stream (clicks:dlq) and are acked away

Run: python -m workers.analytics  (WORKER_NAME env distinguishes consumers)
"""
import asyncio
import logging
import os
import signal
from collections import Counter as CCounter
from datetime import datetime, timezone

from prometheus_client import Counter, Gauge, start_http_server
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError
from sqlalchemy import select

from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.db.upsert import upsert_stmt
from app.models import ClickRollupHourly, Link, ProcessedEvent

log = logging.getLogger("worker.analytics")

EVENTS_PROCESSED = Counter("worker_events_processed_total", "Events counted into rollups")
EVENTS_DUPLICATE = Counter("worker_events_duplicate_total", "Events skipped by idempotency ledger")
EVENTS_SKIPPED = Counter("worker_events_skipped_total", "Events for unknown links")
EVENTS_DLQ = Counter("worker_events_dlq_total", "Events sent to the dead-letter queue")
BATCHES = Counter("worker_batches_total", "Batches processed")
BATCH_FAILURES = Counter("worker_batch_failures_total", "Batches that failed and were not acked")
STREAM_PENDING = Gauge("stream_pending_entries", "Entries pending (unacked) in the consumer group")


def hour_floor(ts_ms: int) -> datetime:
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


class AnalyticsWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.name = os.environ.get("WORKER_NAME") or f"worker-{os.getpid()}"
        self.redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        self.engine = make_engine(self.settings)
        self.sessions = make_sessionmaker(self.engine)
        self.shutting_down = False
        self._link_id_cache: dict[str, int | None] = {}

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                self.settings.stream_key, self.settings.stream_group, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def resolve_link_id(self, session, code: str) -> int | None:
        if code in self._link_id_cache:
            return self._link_id_cache[code]
        row = (await session.execute(select(Link.id).where(Link.short_code == code))).scalar_one_or_none()
        if len(self._link_id_cache) > 50_000:
            self._link_id_cache.clear()
        self._link_id_cache[code] = row
        return row

    async def dlq(self, entry_id: str, fields: dict, reason: str) -> None:
        await self.redis.xadd(
            self.settings.dlq_key,
            {"original_id": entry_id, "reason": reason, **{k: str(v) for k, v in fields.items()}},
        )
        await self.redis.xack(self.settings.stream_key, self.settings.stream_group, entry_id)
        EVENTS_DLQ.inc()

    async def process_batch(self, entries: list[tuple[str, dict]]) -> None:
        """One DB transaction for the whole batch; XACK only after commit."""
        parsed: list[tuple[str, str, int]] = []  # (entry_id, code, ts_ms)
        for entry_id, fields in entries:
            try:
                parsed.append((entry_id, fields["code"], int(fields["ts"])))
            except (KeyError, ValueError):
                await self.dlq(entry_id, fields, "parse_error")
        if not parsed:
            return

        ack_ids = [eid for eid, _, _ in parsed]
        async with self.sessions() as session:
            async with session.begin():
                stmt = (
                    upsert_stmt(session, ProcessedEvent)
                    .values([{"event_id": eid} for eid in ack_ids])
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(ProcessedEvent.event_id)
                )
                new_ids = set((await session.execute(stmt)).scalars().all())
                EVENTS_DUPLICATE.inc(len(ack_ids) - len(new_ids))

                buckets: CCounter = CCounter()
                for eid, code, ts_ms in parsed:
                    if eid not in new_ids:
                        continue
                    link_id = await self.resolve_link_id(session, code)
                    if link_id is None:
                        EVENTS_SKIPPED.inc()
                        continue
                    buckets[(link_id, hour_floor(ts_ms))] += 1

                if buckets:
                    rows = [
                        {"link_id": lid, "bucket_start": bucket, "clicks": n}
                        for (lid, bucket), n in buckets.items()
                    ]
                    upsert = upsert_stmt(session, ClickRollupHourly).values(rows)
                    upsert = upsert.on_conflict_do_update(
                        index_elements=["link_id", "bucket_start"],
                        set_={"clicks": ClickRollupHourly.clicks + upsert.excluded.clicks},
                    )
                    await session.execute(upsert)
            # transaction committed here

        await self.redis.xack(self.settings.stream_key, self.settings.stream_group, *ack_ids)
        EVENTS_PROCESSED.inc(sum(buckets.values()) if parsed else 0)
        BATCHES.inc()

    async def reclaim_stalled(self) -> list[tuple[str, dict]]:
        """XAUTOCLAIM entries idle > min_idle from crashed/slow consumers.
        Entries delivered more than max_deliveries times go to the DLQ."""
        try:
            res = await self.redis.xautoclaim(
                self.settings.stream_key,
                self.settings.stream_group,
                self.name,
                min_idle_time=self.settings.worker_reclaim_min_idle_ms,
                start_id="0-0",
                count=self.settings.worker_batch_size,
            )
        except ResponseError:
            return []
        claimed = res[1] if len(res) >= 2 else []
        if not claimed:
            return []
        # check delivery counts for poison detection
        keep: list[tuple[str, dict]] = []
        pending = await self.redis.xpending_range(
            self.settings.stream_key, self.settings.stream_group,
            min=claimed[0][0], max=claimed[-1][0], count=len(claimed),
        )
        deliveries = {p["message_id"]: p["times_delivered"] for p in pending}
        for entry_id, fields in claimed:
            if deliveries.get(entry_id, 0) > self.settings.worker_max_deliveries:
                await self.dlq(entry_id, fields, "max_deliveries_exceeded")
            else:
                keep.append((entry_id, fields))
        return keep

    async def update_lag_gauge(self) -> None:
        try:
            summary = await self.redis.xpending(self.settings.stream_key, self.settings.stream_group)
            STREAM_PENDING.set(summary.get("pending", 0) if isinstance(summary, dict) else 0)
        except RedisError:
            pass

    async def run(self) -> None:
        await self.ensure_group()
        log.info("worker %s consuming %s/%s", self.name, self.settings.stream_key, self.settings.stream_group)
        loop_n = 0
        while not self.shutting_down:
            try:
                entries: list[tuple[str, dict]] = []
                if loop_n % 10 == 0:
                    entries.extend(await self.reclaim_stalled())
                    await self.update_lag_gauge()
                resp = await self.redis.xreadgroup(
                    self.settings.stream_group,
                    self.name,
                    {self.settings.stream_key: ">"},
                    count=self.settings.worker_batch_size,
                    block=self.settings.worker_block_ms,
                )
                if resp:
                    entries.extend(resp[0][1])
                if entries:
                    await self.process_batch(entries)
                loop_n += 1
            except RedisError as exc:
                log.warning("redis error, backing off: %s", exc)
                BATCH_FAILURES.inc()
                await asyncio.sleep(2)
            except Exception:
                # batch not acked -> entries stay pending -> redelivered / reclaimed
                log.exception("batch failed; entries left pending for redelivery")
                BATCH_FAILURES.inc()
                await asyncio.sleep(2)
        log.info("graceful shutdown complete")
        await self.redis.aclose()
        await self.engine.dispose()

    def request_shutdown(self, *_):
        # finish the current batch, then exit (clean K8s/compose rollouts)
        self.shutting_down = True


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    worker = AnalyticsWorker()
    start_http_server(worker.settings.worker_metrics_port)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.request_shutdown)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
