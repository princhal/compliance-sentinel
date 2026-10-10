"""End to end on the real database: ingest -> audit -> pause -> approve -> PDF, then score it."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select

from evals.score import load_labels, score_findings

pytestmark = pytest.mark.db
FIX = Path(__file__).resolve().parent.parent / "sentinel" / "fixtures" / "regulations"


@pytest.fixture(scope="module")
def completed_run(ingested):
    from sentinel.agent.context import AgentContext
    from sentinel.agent.runner import create_run, resume_audit, run_audit
    from sentinel.db.models import Organization, Repo
    from sentinel.db.session import session_scope

    with session_scope() as s:
        org = s.scalar(select(Organization).where(Organization.clerk_org_id == "org_demo"))
        repo = s.scalar(select(Repo).where(Repo.org_id == org.id))
        org_id, repo_id = org.id, repo.id
    run_id = create_run(org_id, repo_id, "manual", "user_test")
    cp, ctx = InMemorySaver(), AgentContext()
    first = run_audit(run_id, ctx, cp)
    assert "__interrupt__" in first
    with session_scope() as s:
        from sentinel.db.models import AuditRun

        assert s.get(AuditRun, run_id).status == "awaiting_approval"
    resume_audit(run_id, True, "user_auditor", "Ada Auditor", ctx, cp)
    return run_id


def test_ingest_created_obligations_with_exact_citations(ingested):
    from sentinel.db.models import Obligation
    from sentinel.db.session import session_scope

    assert len(ingested["changed_documents"]) == 3
    with session_scope() as s:
        refs = set(s.scalars(select(Obligation.section_ref)))
    assert {"GDPR Art. 32(1)", "CCPA § 1798.105(a)", "HIPAA § 164.312(e)(1)"} <= refs


def test_audit_completes_with_report(completed_run):
    from sentinel.db.models import AuditRun, Report
    from sentinel.db.session import session_scope

    with session_scope() as s:
        run = s.get(AuditRun, completed_run)
        rep = s.scalar(select(Report).where(Report.run_id == run.id))
        assert run.status == "completed" and run.commit
        assert rep.approved_by_name == "Ada Auditor" and len(rep.sha256) == 64
        pdf = Path(rep.pdf_path).read_bytes()
        assert pdf.startswith(b"%PDF")


def test_offline_engine_scores_on_golden_set(completed_run):
    from sentinel.db.models import Finding
    from sentinel.db.session import session_scope

    with session_scope() as s:
        rows = s.scalars(select(Finding).where(Finding.run_id == completed_run))
        findings = [{"path": f.path, "category": f.category, "start_line": f.start_line,
                     "end_line": f.end_line, "status": f.status} for f in rows]
    score = score_findings(findings, load_labels())
    assert score["precision"] == 1.0
    assert score["recall"] >= 0.7
    assert score["decoy_false_alarms"] == []


def test_amendment_adds_only_the_new_obligation(ingested):
    from sentinel.db.models import DocumentVersion, Obligation
    from sentinel.db.session import session_scope
    from sentinel.queue.stages import scrape_and_ingest

    out = scrape_and_ingest(["fixtures"], {"path": str(FIX / "demo-amendments")})
    assert len(out["changed_documents"]) == 1
    with session_scope() as s:
        new = [s.get(Obligation, uuid.UUID(i)) for i in out["new_obligations"]]
        assert new and all(o.section_ref == "GDPR Art. 32(3a)" for o in new)
        assert "secrets_management" in {o.category for o in new}
        v = s.scalar(select(DocumentVersion).where(DocumentVersion.version == 2))
        assert v and "+3a. [SYNTHETIC]" in v.diff
        assert s.scalar(select(func.count()).select_from(Obligation)
                        .where(Obligation.active.is_(False))) == 0
