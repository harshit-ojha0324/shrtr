from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        # "list my links" pagination path
        Index("ix_links_api_key_created", "api_key_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    short_code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    long_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("api_keys.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def is_redirectable(self, now: datetime) -> bool:
        if not self.is_active:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return True
