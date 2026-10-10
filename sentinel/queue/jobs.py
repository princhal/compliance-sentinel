"""Queue names, default job options and helpers to enqueue work."""

from __future__ import annotations

from typing import Any

from bullmq import Queue

from sentinel.config import get_settings

SCRAPE, INGEST, AUDIT, REPORT, NOTIFY, DEAD = "scrape", "ingest", "audit", "report", "notify", "dead-letter"
STAGES = [SCRAPE, INGEST, AUDIT, REPORT, NOTIFY]

JOB_OPTS: dict[str, Any] = {
    "attempts": 3,
    "backoff": {"type": "exponential", "delay": 30_000},
    "removeOnComplete": {"count": 1000},
    "removeOnFail": False,  # Failed jobs stay inspectable; final failures also go to dead-letter.
}


def connection() -> dict[str, Any]:
    return {"connection": get_settings().redis_url}


async def enqueue(queue: str, name: str, data: dict[str, Any],
                  opts: dict[str, Any] | None = None) -> str:
    q = Queue(queue, connection())
    try:
        job = await q.add(name, data, {**JOB_OPTS, **(opts or {})})
        return str(job.id)
    finally:
        await q.close()
