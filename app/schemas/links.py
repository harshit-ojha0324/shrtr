from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from app.services.codegen import is_valid_alias
from app.services.urlcheck import validate_url


class LinkCreate(BaseModel):
    long_url: str = Field(..., examples=["https://example.com/very/long/path"])
    custom_alias: str | None = Field(default=None, examples=["my-link"])
    expires_at: datetime | None = None

    @field_validator("long_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return validate_url(v)  # raises ValueError -> 422

    @field_validator("custom_alias")
    @classmethod
    def _check_alias(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_alias(v):
            raise ValueError("alias must match ^[A-Za-z0-9_-]{4,12}$ and not be a reserved word")
        return v

    @field_validator("expires_at")
    @classmethod
    def _check_expiry(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            # naive datetimes would be silently reinterpreted as UTC by the DB,
            # shifting the expiry by the client's UTC offset
            raise ValueError("expires_at must include a timezone offset, e.g. 2026-01-01T00:00:00Z")
        if v <= datetime.now(timezone.utc):
            raise ValueError("expires_at is in the past")
        return v


class LinkOut(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    is_active: bool
    expires_at: datetime | None
    created_at: datetime


class StatsPoint(BaseModel):
    bucket_start: datetime
    clicks: int


class StatsOut(BaseModel):
    short_code: str
    granularity: str
    total_clicks: int
    series: list[StatsPoint]
    note: str = (
        "Counts are eventually consistent: events are aggregated asynchronously "
        "by stream workers (typically within seconds)."
    )
