"""Registers the daily scrape as a BullMQ job scheduler. Safe to run on every deploy."""

from __future__ import annotations

import logging

from bullmq import Queue

from sentinel.queue import jobs

log = logging.getLogger(__name__)
DAILY = {"pattern": "0 6 * * *", "tz": "UTC"}


async def register_schedules() -> None:
    q = Queue(jobs.SCRAPE, jobs.connection())
    try:
        await q.upsertJobScheduler("daily-scrape", DAILY, "scrape-all", {},
                                   {k: v for k, v in jobs.JOB_OPTS.items()})
        log.info("Registered daily-scrape: %s", DAILY)
    finally:
        await q.close()
