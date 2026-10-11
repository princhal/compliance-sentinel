"""HTTP API for the dashboard. Every query is filtered by the organization from the verified token."""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import uuid
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.api import serialize as ser
from sentinel.api.schemas import ApprovalIn, FindingReviewIn, OrgSettingsIn, RepoIn, RunIn
from sentinel.api.webhooks import router as webhook_router
from sentinel.auth.clerk import ROLE_AUDITOR
from sentinel.auth.deps import OrgContext, current_org, get_db, require_role
from sentinel.config import get_settings
from sentinel.db.models import AuditRun, Document, Finding, Obligation, Repo, Report
from sentinel.queue import jobs
from sentinel.storage import Storage

log = logging.getLogger(__name__)
settings = get_settings()
app = FastAPI(title="Compliance Sentinel API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.clerk_authorized_parties,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(webhook_router)


def _dispatch(background: BackgroundTasks, queue: str, data: dict[str, Any]) -> None:
    """Send work to the queue, or run it in-process when JOBS_INLINE is set (dev and tests)."""
    if get_settings().jobs_inline:
        from sentinel.agent.runner import resume_audit, run_audit

        run_id = uuid.UUID(data["run_id"])
        if resume := data.get("resume"):
            background.add_task(resume_audit, run_id, resume["approved"], resume["approved_by"],
                                resume["approved_by_name"])
        else:
            background.add_task(run_audit, run_id)
        return
    background.add_task(_enqueue_blocking, queue, data)


def _enqueue_blocking(queue: str, data: dict[str, Any]) -> None:
    asyncio.run(jobs.enqueue(queue, queue, data))


def _run_for_org(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> AuditRun:
    run = db.scalar(select(AuditRun).where(AuditRun.id == run_id, AuditRun.org_id == ctx.org.id))
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me")
def me(ctx: OrgContext = Depends(current_org)) -> dict[str, Any]:
    return {"user_id": ctx.principal.user_id, "org_id": ctx.principal.org_id,
            "org_name": ctx.org.name, "role": ctx.principal.role, "name": ctx.user.name,
            "email": ctx.user.email}


# --- Repos -------------------------------------------------------------------------------------


@app.get("/repos")
def list_repos(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)) -> list[dict]:
    return [ser.repo(r) for r in db.scalars(select(Repo).where(Repo.org_id == ctx.org.id)
                                            .order_by(Repo.name))]


@app.post("/repos", status_code=201)
def create_repo(body: RepoIn, ctx: OrgContext = Depends(require_role()),
                db: Session = Depends(get_db)) -> dict:
    if not body.url.startswith("https://") and settings.environment == "production":
        raise HTTPException(422, "Use an https:// git URL")
    if db.scalar(select(Repo).where(Repo.org_id == ctx.org.id, Repo.name == body.name)):
        raise HTTPException(409, "A repo with this name already exists")
    repo = Repo(org_id=ctx.org.id, name=body.name, url=body.url, default_branch=body.default_branch)
    db.add(repo)
    db.flush()
    return ser.repo(repo)


@app.delete("/repos/{repo_id}", status_code=204)
def delete_repo(repo_id: uuid.UUID, ctx: OrgContext = Depends(require_role()),
                db: Session = Depends(get_db)) -> None:
    repo = db.scalar(select(Repo).where(Repo.id == repo_id, Repo.org_id == ctx.org.id))
    if repo is None:
        raise HTTPException(404, "Repo not found")
    db.delete(repo)


# --- Runs --------------------------------------------------------------------------------------


@app.get("/runs")
def list_runs(limit: int = Query(50, le=200), ctx: OrgContext = Depends(current_org),
              db: Session = Depends(get_db)) -> list[dict]:
    runs = list(db.scalars(select(AuditRun).where(AuditRun.org_id == ctx.org.id)
                           .order_by(AuditRun.created_at.desc()).limit(limit)))
    reports = {r.run_id: r for r in db.scalars(select(Report).where(
        Report.run_id.in_([r.id for r in runs])))} if runs else {}
    return [ser.run(r, reports.get(r.id)) for r in runs]


@app.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, ctx: OrgContext = Depends(current_org),
            db: Session = Depends(get_db)) -> dict:
    run = _run_for_org(db, ctx, run_id)
    return ser.run(run, db.scalar(select(Report).where(Report.run_id == run.id)))


@app.post("/runs", status_code=202)
def trigger_run(body: RunIn, background: BackgroundTasks,
                ctx: OrgContext = Depends(require_role()), db: Session = Depends(get_db)) -> dict:
    repo = db.scalar(select(Repo).where(Repo.id == body.repo_id, Repo.org_id == ctx.org.id))
    if repo is None:
        raise HTTPException(404, "Repo not found")
    run = AuditRun(org_id=ctx.org.id, repo_id=repo.id, trigger="manual",
                   triggered_by=ctx.principal.user_id)
    db.add(run)
    db.commit()
    _dispatch(background, jobs.AUDIT, {"run_id": str(run.id)})
    return ser.run(run)


@app.post("/runs/{run_id}/approve", status_code=202)
def approve_run(run_id: uuid.UUID, body: ApprovalIn, background: BackgroundTasks,
                ctx: OrgContext = Depends(require_role(ROLE_AUDITOR)),
                db: Session = Depends(get_db)) -> dict:
    run = _run_for_org(db, ctx, run_id)
    if run.status != "awaiting_approval":
        raise HTTPException(409, f"Run is {run.status}, not awaiting approval")
    run.status = "approving"
    db.commit()
    _dispatch(background, jobs.AUDIT, {"run_id": str(run.id), "resume": {
        "approved": body.approved, "approved_by": ctx.principal.user_id,
        "approved_by_name": ctx.user.name or ctx.user.email or ctx.principal.user_id}})
    return ser.run(run)


# --- Findings ----------------------------------------------------------------------------------


@app.get("/findings")
def list_findings(run_id: uuid.UUID | None = None, severity: str | None = None,
                  status: str | None = None, category: str | None = None,
                  ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Finding).where(Finding.org_id == ctx.org.id)
    if run_id:
        q = q.where(Finding.run_id == run_id)
    if severity:
        q = q.where(Finding.severity == severity)
    if status:
        q = q.where(Finding.status == status)
    if category:
        q = q.where(Finding.category == category)
    return [ser.finding(f) for f in db.scalars(q.order_by(Finding.created_at.desc()).limit(500))]


@app.patch("/findings/{finding_id}")
def review_finding(finding_id: uuid.UUID, body: FindingReviewIn,
                   ctx: OrgContext = Depends(require_role(ROLE_AUDITOR)),
                   db: Session = Depends(get_db)) -> dict:
    from datetime import UTC, datetime

    f = db.scalar(select(Finding).where(Finding.id == finding_id, Finding.org_id == ctx.org.id))
    if f is None:
        raise HTTPException(404, "Finding not found")
    f.review_status, f.reviewed_by, f.reviewed_at = (body.review_status, ctx.principal.user_id,
                                                     datetime.now(UTC))
    return ser.finding(f)


# --- Reports -----------------------------------------------------------------------------------


@app.get("/reports/{report_id}/pdf")
def download_report(report_id: uuid.UUID, ctx: OrgContext = Depends(current_org),
                    db: Session = Depends(get_db)) -> Response:
    rep = db.scalar(select(Report).where(Report.id == report_id, Report.org_id == ctx.org.id))
    if rep is None:
        raise HTTPException(404, "Report not found")
    return Response(Storage().get(rep.pdf_path), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="compliance-report-{rep.run_id}.pdf"',
        "X-Content-SHA256": rep.sha256})


# --- Shared regulations ------------------------------------------------------------------------


@app.get("/regulations")
def list_regulations(ctx: OrgContext = Depends(current_org),
                     db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": str(d.id), "regulation": d.regulation, "title": d.title, "url": d.url,
             "version": d.current_version, "fetched_at": d.fetched_at, "status": d.status}
            for d in db.scalars(select(Document).order_by(Document.regulation))]


@app.get("/obligations")
def list_obligations(regulation: str | None = None, ctx: OrgContext = Depends(current_org),
                     db: Session = Depends(get_db)) -> list[dict]:
    q = select(Obligation).where(Obligation.active.is_(True))
    if regulation:
        q = q.where(Obligation.regulation == regulation)
    rows = db.scalars(q).all()
    return [ser.obligation(o) for o in sorted(rows, key=lambda o: (o.regulation, section_sort_key(o.section_ref)))]


def section_sort_key(ref: str) -> list[str | int]:
    """Orders citations by their numbers, so "Art. 5(1)(c)" sorts before "Art. 44" and "Art. 32(3a)"."""
    # re.split with a capture group alternates text and digits, so items at the same index share a type.
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ref)]


# --- Org settings ------------------------------------------------------------------------------


@app.get("/org/settings")
def get_org_settings(ctx: OrgContext = Depends(current_org)) -> dict:
    return ser.org_settings(ctx.org)


@app.put("/org/settings")
def put_org_settings(body: OrgSettingsIn, ctx: OrgContext = Depends(require_role()),
                     db: Session = Depends(get_db)) -> dict:
    org = db.merge(ctx.org)
    if body.clear_slack:
        org.slack_webhook_url = None
    elif body.slack_webhook_url:
        org.slack_webhook_url = str(body.slack_webhook_url)
    org.alert_emails = {"to": [str(e) for e in body.alert_emails]}
    org.alert_min_severity = body.alert_min_severity
    return ser.org_settings(org)


# --- Internal ----------------------------------------------------------------------------------


@app.post("/internal/scrape", status_code=202)
async def internal_scrape(x_internal_token: str = Header(default="")) -> dict:
    expected = get_settings().internal_api_token
    if not expected or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(401, "Invalid internal token")
    job_id = await jobs.enqueue(jobs.SCRAPE, "scrape-all", {})
    return {"job_id": job_id}
