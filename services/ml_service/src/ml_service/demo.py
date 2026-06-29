"""TEMPORARY end-to-end wiring demo for the ML service.

Proves the plumbing only — NOT part of the real architecture (no hexagonal
layering here). Delete once the real enrollment/inference paths exist.

- POST /temp/ping  -> writes a Postgres row tagged 'ml-service-api'
- background consumer of the Redis stream 'demo-jobs' -> writes rows tagged
  'ml-service-redis' for each job the backend enqueues
"""

import asyncio
import contextlib
import os

import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

STREAM = "demo-jobs"
GROUP = "ml-service"
CONSUMER = "ml-1"

router = APIRouter(prefix="/temp", tags=["temp"])


async def ensure_table() -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_events (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                detail TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.commit()


async def write_event(source: str, detail: str) -> int:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        cur = await conn.execute(
            "INSERT INTO demo_events (source, detail) VALUES (%s, %s) RETURNING id",
            (source, detail),
        )
        row = await cur.fetchone()
        await conn.commit()
        return int(row[0])


@router.post("/ping")
async def ping() -> dict:
    """Called by the backend over HTTP — records that the API path works."""
    event_id = await write_event("ml-service-api", "pinged via HTTP API")
    return {"status": "ok", "via": "api", "event_id": event_id}


async def _consume_loop() -> None:
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    with contextlib.suppress(Exception):
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    try:
        while True:
            try:
                resp = await r.xreadgroup(
                    GROUP, CONSUMER, {STREAM: ">"}, count=10, block=5000
                )
                if not resp:
                    continue
                for _stream, messages in resp:
                    for msg_id, fields in messages:
                        detail = fields.get("detail", "job")
                        await write_event("ml-service-redis", f"consumed: {detail}")
                        await r.xack(STREAM, GROUP, msg_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)
    finally:
        await r.aclose()


def start_consumer() -> "asyncio.Task[None]":
    return asyncio.create_task(_consume_loop())
