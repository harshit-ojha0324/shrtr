from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import charge, get_session, rate_limit, require_api_key
from app.models import ApiKey, ClickRollupDaily, ClickRollupHourly, Link
from app.schemas.links import (
    AliasCheck,
    BulkIn,
    BulkOut,
    BulkResult,
    LinkCreate,
    LinkOut,
    StatsOut,
    StatsPoint,
)
from app.services.codegen import generate_code, is_valid_alias

router = APIRouter(prefix="/api/v1/links", tags=["links"])
# not under /links: /links/{code} would shadow (or be shadowed by) a link named "activity"
misc = APIRouter(prefix="/api/v1", tags=["links"])

MAX_CODE_RETRIES = 5


def _to_out(link: Link, base_url: str) -> LinkOut:
    return LinkOut(
        short_code=link.short_code,
        short_url=f"{base_url.rstrip('/')}/{link.short_code}",
        long_url=link.long_url,
        is_active=link.is_active,
        expires_at=link.expires_at,
        created_at=link.created_at,
    )


async def _create(request: Request, session: AsyncSession, api_key: ApiKey, body: LinkCreate) -> LinkOut:
    """Insert one link: the custom alias as given, or a random code retried on collision."""
    for _ in range(1 if body.custom_alias else MAX_CODE_RETRIES):
        link = Link(
            short_code=body.custom_alias or generate_code(), long_url=body.long_url,
            api_key_id=api_key.id, expires_at=body.expires_at,
        )
        session.add(link)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()  # leaves the session usable for the next row in a bulk call
            continue
        await session.refresh(link)  # load server-generated created_at
        # warm the cache and drop any negative entry a previous miss left behind
        await request.app.state.link_cache.publish(link.short_code, link.long_url, link.expires_at)
        return _to_out(link, request.app.state.settings.base_url)
    if body.custom_alias:
        raise HTTPException(status_code=409, detail="alias already taken")
    raise HTTPException(status_code=500, detail="could not allocate a short code")


@router.post("", status_code=201, response_model=LinkOut)
async def create_link(
    body: LinkCreate,
    request: Request,
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    return await _create(request, session, api_key, body)


@router.post("/bulk", response_model=BulkOut)
async def create_links_bulk(
    body: BulkIn,
    request: Request,
    response: Response,
    api_key: ApiKey = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
):
    """Up to 50 links in one call, each row succeeding or failing on its own.
    Costs one rate-limit token per row, so batching is not a way around the limit."""
    n = len(body.links)
    if n > api_key.rate_capacity:  # could never be allowed: 422, not a 429 to retry forever
        raise HTTPException(422, f"batch of {n} exceeds this key's burst of {api_key.rate_capacity}")
    await charge(request, response, api_key, cost=n)
    results: list[BulkResult] = []
    for i, raw in enumerate(body.links):
        try:
            out = await _create(request, session, api_key, LinkCreate.model_validate(raw))
        except ValidationError as exc:
            msg = exc.errors()[0]["msg"].removeprefix("Value error, ")
            results.append(BulkResult(index=i, ok=False, error=msg))
        except HTTPException as exc:
            results.append(BulkResult(index=i, ok=False, error=str(exc.detail)))
        else:
            results.append(BulkResult(index=i, ok=True, link=out))
    ok = sum(r.ok for r in results)
    return BulkOut(created=ok, failed=n - ok, results=results)


@router.get("", response_model=list[LinkOut])
async def list_links(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    # MVP: limit/offset pagination. Keyset pagination is a documented stretch.
    rows = (
        await session.execute(
            select(Link)
            .where(Link.api_key_id == api_key.id)
            .order_by(Link.created_at.desc(), Link.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return [_to_out(r, request.app.state.settings.base_url) for r in rows]


async def _owned_link(session: AsyncSession, api_key: ApiKey, code: str) -> Link:
    row = (
        await session.execute(
            select(Link).where(Link.short_code == code, Link.api_key_id == api_key.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="link not found")
    return row


@router.get("/{code}", response_model=LinkOut)
async def get_link(
    code: str,
    request: Request,
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    link = await _owned_link(session, api_key, code)
    return _to_out(link, request.app.state.settings.base_url)


@router.delete("/{code}", status_code=204)
async def delete_link(
    code: str,
    request: Request,
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    link = await _owned_link(session, api_key, code)
    link.is_active = False
    await session.commit()
    await request.app.state.link_cache.tombstone(code)


@router.get("/{code}/stats", response_model=StatsOut)
async def link_stats(
    code: str,
    granularity: str = Query(default="hour", pattern="^(hour|day)$"),
    frm: AwareDatetime | None = Query(default=None, alias="from"),  # naive = ambiguous -> 422
    to: AwareDatetime | None = Query(default=None),
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    link = await _owned_link(session, api_key, code)
    now = datetime.now(timezone.utc)
    if to is None:
        to = now
    if frm is None:
        frm = now - (timedelta(hours=24) if granularity == "hour" else timedelta(days=30))

    async def buckets(table, start, end):
        return (
            await session.execute(
                select(table.bucket_start, table.clicks)
                .where(table.link_id == link.id, table.bucket_start >= start, table.bucket_start < end)
                .order_by(table.bucket_start)
            )
        ).all()

    if granularity == "hour":
        rows = await buckets(ClickRollupHourly, frm, to)
    else:
        # daily rows come from the hourly `rollup` job, so today and yesterday can
        # lag by up to an hour: sum those two days from the hourly table (<= 48 rows)
        fresh = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        rows = list(await buckets(ClickRollupDaily, frm, min(to, fresh)))
        recent: dict[datetime, int] = {}
        for b, c in await buckets(ClickRollupHourly, max(frm, fresh), to):
            day = b.replace(hour=0, minute=0, second=0, microsecond=0)
            recent[day] = recent.get(day, 0) + c
        rows += sorted(recent.items())
    series = [StatsPoint(bucket_start=b, clicks=c) for b, c in rows]
    return StatsOut(
        short_code=code,
        granularity=granularity,
        total_clicks=sum(p.clicks for p in series),
        series=series,
    )


@misc.get("/activity", response_model=dict[str, list[StatsPoint]])
async def activity(
    hours: int = Query(default=24, ge=1, le=168),
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    """Hourly clicks for every link of this key in one query (the web app's list
    sparklines), instead of one stats call per link. Links with no clicks are omitted."""
    since = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    rows = await session.execute(
        select(Link.short_code, ClickRollupHourly.bucket_start, ClickRollupHourly.clicks)
        .join(Link, Link.id == ClickRollupHourly.link_id)
        .where(Link.api_key_id == api_key.id, ClickRollupHourly.bucket_start >= since)
        .order_by(ClickRollupHourly.bucket_start)
    )
    out: dict[str, list[StatsPoint]] = {}
    for code, b, c in rows:
        out.setdefault(code, []).append(StatsPoint(bucket_start=b, clicks=c))
    return out


@misc.get("/aliases/{alias}", response_model=AliasCheck)
async def check_alias(
    alias: str,
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    """Is this custom alias free? Powers the live check in the create form."""
    if not is_valid_alias(alias):
        return AliasCheck(alias=alias, available=False, reason="use 3-32 letters, digits, - or _")
    taken = await session.scalar(select(Link.id).where(Link.short_code == alias))
    return AliasCheck(alias=alias, available=taken is None, reason=None if taken is None else "already taken")
