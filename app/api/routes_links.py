from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, rate_limit
from app.models import ApiKey, ClickRollupDaily, ClickRollupHourly, Link
from app.schemas import LinkCreate, LinkOut, StatsOut, StatsPoint
from app.services.codegen import generate_code

router = APIRouter(prefix="/api/v1/links", tags=["links"])

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


def _apply_rate_headers(request: Request, response: Response) -> None:
    for k, v in getattr(request.state, "rate_headers", {}).items():
        response.headers[k] = v


@router.post("", status_code=201, response_model=LinkOut)
async def create_link(
    body: LinkCreate,
    request: Request,
    response: Response,
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    settings = request.app.state.settings
    if body.custom_alias:
        link = Link(
            short_code=body.custom_alias, long_url=body.long_url,
            api_key_id=api_key.id, expires_at=body.expires_at,
        )
        session.add(link)
        try:
            await session.commit()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="alias already taken")
        await session.refresh(link)  # load server-generated created_at
    else:
        link = None
        for _ in range(MAX_CODE_RETRIES):
            candidate = Link(
                short_code=generate_code(), long_url=body.long_url,
                api_key_id=api_key.id, expires_at=body.expires_at,
            )
            session.add(candidate)
            try:
                await session.commit()
                link = candidate
                break
            except IntegrityError:
                await session.rollback()
        if link is None:
            raise HTTPException(status_code=500, detail="could not allocate a short code")
        await session.refresh(link)  # load server-generated created_at
    # a previous miss may have negative-cached this code
    await request.app.state.link_cache.invalidate(link.short_code)
    _apply_rate_headers(request, response)
    return _to_out(link, settings.base_url)


@router.get("", response_model=list[LinkOut])
async def list_links(
    request: Request,
    response: Response,
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
    _apply_rate_headers(request, response)
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
    response: Response,
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    link = await _owned_link(session, api_key, code)
    _apply_rate_headers(request, response)
    return _to_out(link, request.app.state.settings.base_url)


@router.delete("/{code}", status_code=204)
async def delete_link(
    code: str,
    request: Request,
    response: Response,
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    link = await _owned_link(session, api_key, code)
    link.is_active = False
    await session.commit()
    cache = request.app.state.link_cache
    await cache.invalidate(code)   # drop stale positive entry
    await cache.set_negative(code)  # stop redirects within negative TTL
    _apply_rate_headers(request, response)


@router.get("/{code}/stats", response_model=StatsOut)
async def link_stats(
    code: str,
    request: Request,
    response: Response,
    granularity: str = Query(default="hour", pattern="^(hour|day)$"),
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    api_key: ApiKey = Depends(rate_limit),
    session: AsyncSession = Depends(get_session),
):
    link = await _owned_link(session, api_key, code)
    now = datetime.now(timezone.utc)
    if to is None:
        to = now
    if frm is None:
        frm = now - (timedelta(hours=24) if granularity == "hour" else timedelta(days=30))
    table = ClickRollupHourly if granularity == "hour" else ClickRollupDaily
    rows = (
        await session.execute(
            select(table.bucket_start, table.clicks)
            .where(table.link_id == link.id, table.bucket_start >= frm, table.bucket_start < to)
            .order_by(table.bucket_start)
        )
    ).all()
    series = [StatsPoint(bucket_start=b, clicks=c) for b, c in rows]
    _apply_rate_headers(request, response)
    return StatsOut(
        short_code=code,
        granularity=granularity,
        total_clicks=sum(p.clicks for p in series),
        series=series,
    )
