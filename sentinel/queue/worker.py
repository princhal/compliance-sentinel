"""BullMQ workers. Each stage enqueues the next one, so any stage can be retried or replayed alone.

scrape -> ingest -> audit -> (report, notify run inside the audit graph; their queues re-run them
on demand).
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from typing import Any

from bullmq import Job, Queue, Worker

from sentinel.queue import jobs, stages

log = logging.getLogger(__name__)


async def process_scrape(job: Job, token: str) -> dict[str, Any]:
    docs = await asyncio.to_thread(stages.scrape, job.data.get("source_keys"),
                                   job.data.get("override"))
    if docs:
        await jobs.enqueue(jobs.INGEST, "ingest", {"document_ids": docs})
    return {"changed_documents": docs}


async def process_ingest(job: Job, token: str) -> dict[str, Any]:
    from sentinel.agent.runner import create_run

    new = await asyncio.to_thread(stages.ingest, job.data["document_ids"])
    runs = []
    if new:
        for org_id, repo_id in await asyncio.to_thread(stages.repos_to_reaudit):
            run_id = await asyncio.to_thread(create_run, uuid.UUID(org_id), uuid.UUID(repo_id),
                                             "regulation_change", None, new)
            await jobs.enqueue(jobs.AUDIT, "audit", {"run_id": str(run_id)})
            runs.append(str(run_id))
    return {"new_obligations": len(new), "audit_runs": runs}


async def process_audit(job: Job, token: str) -> dict[str, Any]:
    from sentinel.agent.runner import resume_audit, run_audit

    run_id = uuid.UUID(job.data["run_id"])
    if resume := job.data.get("resume"):
        await asyncio.to_thread(resume_audit, run_id, resume["approved"], resume.get("approved_by"),
                                resume.get("approved_by_name"))
    else:
        await asyncio.to_thread(run_audit, run_id)
    return {"run_id": str(run_id)}


async def process_report(job: Job, token: str) -> dict[str, Any]:
    from sentinel.db.session import session_scope
    from sentinel.report.render import build_report
    from sentinel.storage import Storage

    def _build() -> str:
        with session_scope() as s:
            return str(build_report(s, uuid.UUID(job.data["run_id"]), Storage(),
                                    job.data.get("approved_by"),
                                    job.data.get("approved_by_name")).id)

    return {"report_id": await asyncio.to_thread(_build)}


async def process_notify(job: Job, token: str) -> dict[str, Any]:
    await asyncio.to_thread(stages.notify_run, uuid.UUID(job.data["run_id"]))
    return {"run_id": job.data["run_id"]}


PROCESSORS = {jobs.SCRAPE: process_scrape, jobs.INGEST: process_ingest, jobs.AUDIT: process_audit,
              jobs.REPORT: process_report, jobs.NOTIFY: process_notify}
CONCURRENCY = {jobs.SCRAPE: 1, jobs.INGEST: 1, jobs.AUDIT: 2, jobs.REPORT: 2, jobs.NOTIFY: 4}


async def run_workers() -> None:
    dead = Queue(jobs.DEAD, jobs.connection())
    workers: list[Worker] = []
    for name, fn in PROCESSORS.items():
        w = Worker(name, fn, {**jobs.connection(), "concurrency": CONCURRENCY[name],
                              "lockDuration": 300_000})

        def on_failed(job: Job, err: Exception, queue_name: str = name) -> None:
            log.error("Job %s on %s failed (attempt %s): %s", job.id, queue_name,
                      job.attemptsMade, err)
            if job.attemptsMade >= int(job.opts.get("attempts", 1)):
                asyncio.ensure_future(dead.add("dead", {"queue": queue_name, "job_id": job.id,
                                                        "data": job.data, "error": str(err)}))

        w.on("failed", on_failed)
        workers.append(w)
    log.info("Workers running for queues: %s", ", ".join(PROCESSORS))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    for w in workers:
        await w.close()
    await dead.close()
