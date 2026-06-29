"""TEMPORARY end-to-end wiring demo for the backend (core system).

Proves the plumbing only. Delete once real routes exist.

- POST /temp/run : writes its own Postgres row ('backend'), calls the ML service
  over HTTP (/temp/ping), and enqueues a Redis job the ML service consumes.
  After a run you should see three sources in Postgres: 'backend',
  'ml-service-api', and 'ml-service-redis'.
- GET  /temp/events : lists recent rows so the result is verifiable.
"""

import os

import httpx
import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://ml-service:8000")

STREAM = "demo-jobs"

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


@router.post("/run")
async def run() -> dict:
    result: dict = {"status": "ok"}

    # 1) Backend writes its own row in Postgres.
    result["backend_db_event_id"] = await write_event("backend", "demo run from backend")

    # 2) Backend calls the ML service over HTTP (API path).
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{ML_SERVICE_URL}/temp/ping")
        resp.raise_for_status()
        result["ml_service_api"] = resp.json()

    # 3) Backend enqueues a job on Redis (queue path -> ML service consumer).
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        msg_id = await r.xadd(STREAM, {"detail": "demo job from backend"})
    finally:
        await r.aclose()
    result["queue_message_id"] = msg_id

    return result


@router.get("/events")
async def events() -> dict:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        cur = await conn.execute(
            "SELECT id, source, detail, created_at "
            "FROM demo_events ORDER BY id DESC LIMIT 20"
        )
        rows = await cur.fetchall()
    return {
        "events": [
            {
                "id": row[0],
                "source": row[1],
                "detail": row[2],
                "created_at": row[3].isoformat(),
            }
            for row in rows
        ]
    }
