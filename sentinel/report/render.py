"""Build the audit-ready PDF report for one run.

The PDF shows a SHA-256 digest of a canonical JSON manifest of the run (scope, citations and
findings). Anyone holding the database row can recompute it. The SHA-256 of the PDF file itself
is stored on the Report row and next to the file, since a file cannot contain its own hash.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.db.models import (
    AuditRun,
    Document,
    DocumentVersion,
    Finding,
    Obligation,
    Organization,
    Report,
)
from sentinel.storage import Storage
from sentinel.taxonomy import CATEGORIES, severity_rank

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def build_context(session: Session, run_id: uuid.UUID) -> dict:
    run = session.get(AuditRun, run_id)
    org = session.get(Organization, run.org_id)
    findings = sorted(session.scalars(select(Finding).where(Finding.run_id == run.id)),
                      key=lambda f: (f.status != "violation", severity_rank(f.severity), f.path,
                                     f.start_line))
    cited_ids = {uuid.UUID(c["obligation_id"]) for f in findings for c in f.citations}
    doc_ids = set(session.scalars(select(Obligation.document_id).where(
        Obligation.id.in_(cited_ids)))) if cited_ids else set()
    in_scope_docs = list(session.scalars(select(Document).where(Document.status == "ingested")
                                         .order_by(Document.regulation)))
    changed = []
    for d in in_scope_docs:
        if d.current_version > 1:
            v = session.scalar(select(DocumentVersion).where(
                DocumentVersion.document_id == d.id, DocumentVersion.version == d.current_version))
            if v and v.diff:
                changed.append({"doc": d, "version": v.version, "diff": v.diff[:6000]})
    by_sev = Counter(f.severity for f in findings if f.status == "violation")
    by_status = Counter(f.status for f in findings)
    by_cat = Counter(CATEGORIES[f.category].label for f in findings if f.status == "violation")
    manifest = {
        "run_id": str(run.id), "org": org.clerk_org_id, "repo": run.repo.name,
        "commit": run.commit, "engine": run.llm_engine,
        "documents": [{"id": d.external_id, "version": d.current_version, "sha256": d.content_hash}
                      for d in in_scope_docs],
        "findings": [{"category": f.category, "path": f.path, "lines": [f.start_line, f.end_line],
                      "status": f.status, "severity": f.severity, "confidence": f.confidence,
                      "citations": sorted(c["section_ref"] for c in f.citations)}
                     for f in findings],
    }
    manifest_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"run": run, "org": org, "repo": run.repo, "findings": findings,
            "violations": [f for f in findings if f.status == "violation"],
            "reviews": [f for f in findings if f.status == "needs_review"],
            "documents": in_scope_docs, "cited_doc_ids": doc_ids, "changed": changed,
            "by_sev": by_sev, "by_status": by_status, "by_cat": by_cat.most_common(6),
            "categories": CATEGORIES, "manifest_sha": manifest_sha,
            "generated_at": datetime.now(UTC)}


def render_html(ctx: dict, approved_by_name: str | None, approved_at: datetime | None) -> str:
    return _env.get_template("report.html").render(
        **ctx, approved_by_name=approved_by_name, approved_at=approved_at)


def build_report(session: Session, run_id: uuid.UUID, storage: Storage,
                 approved_by: str | None = None, approved_by_name: str | None = None) -> Report:
    from weasyprint import HTML

    ctx = build_context(session, run_id)
    approved_at = datetime.now(UTC) if approved_by else None
    html = render_html(ctx, approved_by_name or approved_by, approved_at)
    pdf = HTML(string=html, base_url=str(TEMPLATES)).write_pdf()
    sha = hashlib.sha256(pdf).hexdigest()
    run = ctx["run"]
    key = f"reports/{run.org_id}/{run.id}.pdf"
    ref = storage.put(key, pdf, "application/pdf")
    storage.put(key + ".sha256", f"{sha}  {run.id}.pdf\n".encode(), "text/plain")
    report = Report(org_id=run.org_id, run_id=run.id, pdf_path=ref, sha256=sha,
                    manifest_sha256=ctx["manifest_sha"], approved_by=approved_by,
                    approved_by_name=approved_by_name, approved_at=approved_at)
    session.add(report)
    session.flush()
    return report
