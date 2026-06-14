from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ClickRollupHourly(Base):
    __tablename__ = "click_rollups_hourly"

    link_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("links.id"), primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class ClickRollupDaily(Base):
    __tablename__ = "click_rollups_daily"

    link_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("links.id"), primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class ProcessedEvent(Base):
    """Idempotency ledger: stream entry IDs we have already counted.

    At-least-once delivery (Redis Streams PEL) + this ledger = effectively-once counting.
    Purged periodically (see workers/rollup_daily.py).
    """

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
