"""Start and resume audit runs. The Postgres checkpointer lets a paused run resume in any process."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from sentinel.agent.context import AgentContext
from sentinel.agent.graph import build_graph
from sentinel.db.models import AuditRun
from sentinel.db.session import psycopg_url, session_scope

log = logging.getLogger(__name__)


@contextmanager
def checkpointer(database_url: str | None = None) -> Iterator[Any]:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(psycopg_url(database_url)) as cp:
        cp.setup()
        yield cp


def create_run(org_id: uuid.UUID, repo_id: uuid.UUID, trigger: str,
               triggered_by: str | None = None, obligation_ids: list[str] | None = None,
               database_url: str | None = None) -> uuid.UUID:
    with session_scope(database_url) as s:
        run = AuditRun(org_id=org_id, repo_id=repo_id, trigger=trigger, triggered_by=triggered_by,
                       mode="changed" if obligation_ids else "full",
                       stats={"obligation_ids": obligation_ids} if obligation_ids else {})
        s.add(run)
        s.flush()
        return run.id


def _config(run_id: uuid.UUID) -> dict:
    return {"configurable": {"thread_id": str(run_id)}, "max_concurrency": 4}


def run_audit(run_id: uuid.UUID, ctx: AgentContext | None = None, cp: Any = None) -> dict:
    ctx = ctx or AgentContext()
    with session_scope(ctx.database_url) as s:
        run = s.get(AuditRun, run_id)
        state = {"run_id": str(run.id), "org_id": str(run.org_id), "repo_id": str(run.repo_id),
                 "obligation_ids": (run.stats or {}).get("obligation_ids"), "findings": [],
                 "errors": []}
    try:
        if cp is not None:
            return build_graph(cp).invoke(state, _config(run_id), context=ctx)
        with checkpointer(ctx.database_url) as saver:
            return build_graph(saver).invoke(state, _config(run_id), context=ctx)
    except Exception as exc:
        _fail(run_id, exc, ctx.database_url)
        raise


def resume_audit(run_id: uuid.UUID, approved: bool, approved_by: str | None,
                 approved_by_name: str | None, ctx: AgentContext | None = None,
                 cp: Any = None) -> dict:
    ctx = ctx or AgentContext()
    decision = Command(resume={"approved": approved, "approved_by": approved_by,
                               "approved_by_name": approved_by_name})
    try:
        if cp is not None:
            return build_graph(cp).invoke(decision, _config(run_id), context=ctx)
        with checkpointer(ctx.database_url) as saver:
            return build_graph(saver).invoke(decision, _config(run_id), context=ctx)
    except Exception as exc:
        _fail(run_id, exc, ctx.database_url)
        raise


def _fail(run_id: uuid.UUID, exc: Exception, database_url: str | None) -> None:
    log.exception("Audit run %s failed", run_id)
    with session_scope(database_url) as s:
        run = s.get(AuditRun, run_id)
        if run is not None:
            run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"[:4000]
            run.finished_at = datetime.now(UTC)
