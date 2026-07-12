"""Daily rollup + retention job (one-shot; run via `make rollup` or cron).

1. Aggregates hourly rollups into click_rollups_daily (idempotent upsert).
2. Purges processed_events older than 48h (the stream is trimmed to ~1M entries,
   so older entry IDs can never be redelivered).

Scheduling this automatically (cron container / K8s CronJob) is a documented stretch.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.db.upsert import upsert_stmt
from app.models import ClickRollupDaily, ClickRollupHourly, ProcessedEvent


async def run(days_back: int = 2) -> None:
    settings = get_settings()
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days_back
    )
    async with sessions() as session:
        async with session.begin():
            day = func.date_trunc("day", ClickRollupHourly.bucket_start)
            rows = (
                await session.execute(
                    select(
                        ClickRollupHourly.link_id,
                        day.label("bucket_start"),
                        func.sum(ClickRollupHourly.clicks).label("clicks"),
                    )
                    .where(ClickRollupHourly.bucket_start >= since)
                    .group_by(ClickRollupHourly.link_id, day)
                )
            ).all()
            if rows:
                upsert = upsert_stmt(session, ClickRollupDaily).values(
                    [
                        {"link_id": r.link_id, "bucket_start": r.bucket_start, "clicks": int(r.clicks)}
                        for r in rows
                    ]
                )
                upsert = upsert.on_conflict_do_update(
                    index_elements=["link_id", "bucket_start"],
                    set_={"clicks": upsert.excluded.clicks},  # recompute, don't add (idempotent)
                )
                await session.execute(upsert)
            purged = await session.execute(
                delete(ProcessedEvent).where(
                    ProcessedEvent.processed_at < datetime.now(timezone.utc) - timedelta(hours=48)
                )
            )
            print(f"daily rollup: upserted {len(rows)} day-buckets, purged {purged.rowcount} ledger rows")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
