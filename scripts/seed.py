"""Seed a demo API key and sample links.

Usage:
    python -m scripts.seed                # demo key + 20 sample links
    python -m scripts.seed --links 10000  # also useful before load testing

The raw API key is printed ONCE (only its SHA-256 is stored). For local demos a
deterministic key can be forced with SEED_API_KEY=... so `make seed` is repeatable.
Codes are written to load/codes.json for the k6 script.
"""
import argparse
import asyncio
import hashlib
import json
import os
import secrets
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.models import ApiKey, Link
from app.services.codegen import generate_code

SAMPLE_URLS = [
    "https://example.com/welcome",
    "https://www.postgresql.org/docs/current/indexes.html",
    "https://redis.io/docs/latest/develop/data-types/streams/",
    "https://fastapi.tiangolo.com/tutorial/",
    "https://grafana.com/docs/k6/latest/",
]


async def main(n_links: int) -> None:
    settings = get_settings()
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)

    raw_key = os.environ.get("SEED_API_KEY") or secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw_key.encode()).hexdigest()

    async with sessions() as session:
        existing = (
            await session.execute(select(ApiKey).where(ApiKey.key_hash == digest))
        ).scalar_one_or_none()
        if existing:
            key = existing
            print("demo API key already seeded (same SEED_API_KEY)")
        else:
            key = ApiKey(key_hash=digest, name="demo", rate_capacity=60, refill_per_s=1.0)
            session.add(key)
            await session.flush()

        codes: list[str] = []
        for i in range(n_links):
            code = generate_code()
            session.add(
                Link(
                    short_code=code,
                    long_url=SAMPLE_URLS[i % len(SAMPLE_URLS)],
                    api_key_id=key.id,
                )
            )
            codes.append(code)
        await session.commit()

    out = Path(__file__).resolve().parent.parent / "load" / "codes.json"
    try:
        out.write_text(json.dumps(codes))
        print(f"wrote {len(codes)} codes to {out}")
    except OSError as exc:
        print(f"could not write codes.json ({exc}); printing first 5: {codes[:5]}")

    print("\n=== DEMO API KEY (shown once, store it) ===")
    print(raw_key)
    print("===========================================")
    print(f'try:  curl -X POST {settings.base_url}/api/v1/links -H "X-API-Key: {raw_key}" '
          f'-H "Content-Type: application/json" -d \'{{"long_url":"https://example.com"}}\'')
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--links", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.links))
