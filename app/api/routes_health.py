from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    """Liveness: process is up."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response):
    """Readiness: dependencies reachable."""
    checks = {}
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "down"
    if any(v != "ok" for v in checks.values()):
        response.status_code = 503
    return checks
