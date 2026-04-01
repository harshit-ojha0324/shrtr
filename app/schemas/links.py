from datetime import datetime

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
