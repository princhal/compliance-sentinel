"""Plain-dict views of database rows for JSON responses."""

from __future__ import annotations

from typing import Any

from sentinel.db.models import AuditRun, Finding, Obligation, Organization, Repo, Report
from sentinel.taxonomy import CATEGORIES


def repo(r: Repo) -> dict[str, Any]:
    return {"id": str(r.id), "name": r.name, "url": r.url, "default_branch": r.default_branch,
            "last_commit": r.last_commit, "last_indexed_at": r.last_indexed_at}


def run(r: AuditRun, report: Report | None = None) -> dict[str, Any]:
    return {"id": str(r.id), "repo_id": str(r.repo_id), "repo_name": r.repo.name if r.repo else None,
            "commit": r.commit, "trigger": r.trigger, "triggered_by": r.triggered_by,
            "mode": r.mode, "status": r.status, "created_at": r.created_at,
            "started_at": r.started_at, "finished_at": r.finished_at, "engine": r.llm_engine,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
            "cost_usd": r.cost_usd, "stats": r.stats, "error": r.error,
            "report": ({"id": str(report.id), "sha256": report.sha256,
                        "approved_by_name": report.approved_by_name,
                        "approved_at": report.approved_at} if report else None)}


def finding(f: Finding) -> dict[str, Any]:
    return {"id": str(f.id), "run_id": str(f.run_id), "category": f.category,
            "label": CATEGORIES[f.category].label, "path": f.path, "start_line": f.start_line,
            "end_line": f.end_line, "severity": f.severity, "status": f.status,
            "review_status": f.review_status, "rule_id": f.rule_id, "evidence": f.evidence,
            "reasoning": f.reasoning, "confidence": f.confidence, "citations": f.citations,
            "reviewed_by": f.reviewed_by, "reviewed_at": f.reviewed_at}


def obligation(o: Obligation) -> dict[str, Any]:
    return {"id": str(o.id), "regulation": o.regulation, "section_ref": o.section_ref,
            "category": o.category, "severity": o.severity, "summary": o.summary,
            "quote": o.quote, "source_url": o.source_url, "code_checkable": o.code_checkable,
            "created_at": o.created_at}


def org_settings(o: Organization) -> dict[str, Any]:
    return {"name": o.name, "slack_webhook_configured": bool(o.slack_webhook_url),
            "alert_emails": o.alert_emails.get("to", []),
            "alert_min_severity": o.alert_min_severity}
