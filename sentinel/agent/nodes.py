"""Graph nodes. Each opens its own short database transaction."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Send, interrupt
from sqlalchemy import select

from sentinel.agent.context import AgentContext
from sentinel.agent.state import AuditState, GroupState
from sentinel.codebase.checks import run_checks
from sentinel.codebase.index import index_repo, read_lines
from sentinel.db.models import AlertLog, AuditRun, Finding, Obligation, Organization, Repo
from sentinel.db.session import session_scope
from sentinel.llm import AssessedItem, EvidenceItem, LLMRefusal, ObligationView
from sentinel.notify.notifier import Alert
from sentinel.rag.retriever import search_code
from sentinel.taxonomy import CATEGORIES, severity_rank

log = logging.getLogger(__name__)
MAX_SEARCH_EVIDENCE = 6


def _db(runtime: Runtime[AgentContext]):
    return session_scope(runtime.context.database_url)


def _set_status(runtime: Runtime[AgentContext], run_id: str, **fields: Any) -> None:
    with _db(runtime) as s:
        run = s.get(AuditRun, uuid.UUID(run_id))
        for k, v in fields.items():
            setattr(run, k, v)


# --- 1. Load obligations ------------------------------------------------------------------


def load_obligations(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    _set_status(runtime, state["run_id"], status="running", started_at=datetime.now(UTC),
                llm_engine=runtime.context.engine.name)
    with _db(runtime) as s:
        q = select(Obligation).where(Obligation.active.is_(True),
                                     Obligation.code_checkable.is_(True))
        if state.get("obligation_ids"):
            q = q.where(Obligation.id.in_([uuid.UUID(i) for i in state["obligation_ids"]]))
        obligations = [{
            "id": str(o.id), "regulation": o.regulation, "section_ref": o.section_ref,
            "category": o.category, "severity": o.severity, "summary": o.summary,
            "quote": o.quote, "source_url": o.source_url,
            "retrieved_at": o.retrieved_at.isoformat(),
        } for o in s.scalars(q.order_by(Obligation.regulation, Obligation.section_ref))]
    return {"obligations": obligations}


# --- 2. Index the repo and run static checks ----------------------------------------------


def index_and_scan(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    with _db(runtime) as s:
        repo = s.get(Repo, uuid.UUID(state["repo_id"]))
        result = index_repo(s, repo, runtime.context.embedder, runtime.context.settings)
        run = s.get(AuditRun, uuid.UUID(state["run_id"]))
        run.commit = result.commit
    hits = [h.to_dict() for h in run_checks(result.workdir)]
    return {"workdir": str(result.workdir), "commit": result.commit, "static_hits": hits}


def fan_out(state: AuditState) -> list[Send] | str:
    """One parallel check per category that has at least one obligation."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for ob in state.get("obligations", []):
        groups[ob["category"]].append(ob)
    if not groups:
        return "aggregate"
    return [Send("check_category", {
        "category": cat, "obligations": obs,
        "hits": [h for h in state["static_hits"] if h["category"] == cat],
        "repo_id": state["repo_id"], "commit": state["commit"], "workdir": state["workdir"],
    }) for cat, obs in sorted(groups.items())]


# --- 3. Per-category subgraph: plan -> retrieve -> assess -> verify ----------------------


def _primary(state: GroupState) -> ObligationView:
    """The most severe obligation speaks for the group; the rest become extra citations."""
    obs = sorted(state["obligations"], key=lambda o: severity_rank(o["severity"]))
    top = obs[0]
    others = "; ".join(f"{o['section_ref']}: {o['quote'][:200]}" for o in obs[1:4])
    return ObligationView(regulation=top["regulation"], section_ref=top["section_ref"],
                          category=state["category"], severity=top["severity"],
                          summary=top["summary"] + (f" Related duties: {others}" if others else ""),
                          quote=top["quote"])


def plan_checks(state: GroupState, runtime: Runtime[AgentContext]) -> dict:
    try:
        plan = runtime.context.engine.plan_checks(_primary(state))
        return {"queries": plan.search_queries[:5]}
    except LLMRefusal as exc:
        return {"queries": list(CATEGORIES[state["category"]].code_terms[:3]),
                "errors": [f"plan_checks refused for {state['category']}: {exc}"]}


def retrieve_code(state: GroupState, runtime: Runtime[AgentContext]) -> dict:
    workdir = Path(state["workdir"])
    evidence: list[dict] = []
    covered: dict[str, set[int]] = defaultdict(set)
    for h in state["hits"]:
        evidence.append({"id": f"E{len(evidence) + 1}", "path": h["path"],
                         "start_line": h["start_line"], "end_line": h["end_line"],
                         "snippet": read_lines(workdir, h["path"], h["start_line"], h["end_line"],
                                               pad=2) or h["snippet"],
                         "source": h["rule_id"], "message": h["message"],
                         "rule_confidence": h["confidence"]})
        covered[h["path"]].update(range(h["start_line"] - 3, h["end_line"] + 4))
    added = 0
    with _db(runtime) as s:
        for query in state.get("queries", []):
            for hit in search_code(s, runtime.context.embedder, uuid.UUID(state["repo_id"]),
                                   state["commit"], query, k=3,
                                   settings=runtime.context.settings):
                c = hit.row
                if added >= MAX_SEARCH_EVIDENCE or set(range(c.start_line, c.end_line + 1)) & \
                        covered[c.path]:
                    continue
                covered[c.path].update(range(c.start_line, c.end_line + 1))
                end = min(c.end_line, c.start_line + 59)
                evidence.append({"id": f"E{len(evidence) + 1}", "path": c.path,
                                 "start_line": c.start_line, "end_line": end,
                                 "snippet": read_lines(workdir, c.path, c.start_line, end),
                                 "source": "search", "message": f"Code search: {query}",
                                 "rule_confidence": 0.0})
                added += 1
    return {"evidence": evidence}


def assess(state: GroupState, runtime: Runtime[AgentContext]) -> dict:
    evidence = [EvidenceItem(**e) for e in state.get("evidence", [])]
    try:
        items = runtime.context.engine.assess(_primary(state), evidence)
    except LLMRefusal as exc:
        return {"assessed": [], "errors": [f"assess refused for {state['category']}: {exc}"]}
    return {"assessed": [i.model_dump() for i in items]}


def _narrow(snippet_lines: list[str], category: str) -> int | None:
    """For a search-evidence finding, point at the most relevant line inside the chunk."""
    terms = CATEGORIES[category].code_terms
    for line in snippet_lines:
        m = re.match(r"\s*(\d+) \| (.*)", line)
        if m and any(t.lower() in m.group(2).lower() for t in terms):
            return int(m.group(1))
    return None


def verify(state: GroupState, runtime: Runtime[AgentContext]) -> dict:
    """Second pass. Locations always come from real evidence; a skeptical review can downgrade a
    violation to needs_review, and low confidence always means needs_review."""
    ctx = runtime.context
    workdir = Path(state["workdir"])
    by_id = {e["id"]: e for e in state.get("evidence", [])}
    view = _primary(state)
    findings, errors = [], []
    for raw in state.get("assessed", []):
        item = AssessedItem(**raw)
        ev = by_id.get(item.evidence_id)
        if ev is None or item.status == "compliant":
            continue
        status, confidence, reasoning = item.status, max(0.0, min(1.0, item.confidence)), item.reasoning
        if status == "violation":
            excerpt = read_lines(workdir, ev["path"], ev["start_line"], ev["end_line"], pad=8)
            try:
                check = ctx.engine.verify(view, item, EvidenceItem(**ev), excerpt)
                if not check.confirmed:
                    status = "needs_review"
                    reasoning += f" Second review: {check.reason}"
                confidence = min(confidence, max(0.0, min(1.0, check.confidence)))
            except LLMRefusal as exc:
                status = "needs_review"
                errors.append(f"verify refused at {ev['path']}:{ev['start_line']}: {exc}")
        if confidence < ctx.settings.confidence_threshold:
            status = "needs_review"
        start, end = ev["start_line"], ev["end_line"]
        if ev["source"] == "search":
            line = _narrow(ev["snippet"].splitlines(), state["category"])
            if line:
                start = end = line
        findings.append({
            "category": state["category"], "path": ev["path"], "start_line": start,
            "end_line": end, "severity": item.severity, "status": status,
            "confidence": round(confidence, 3), "reasoning": reasoning,
            "rule_id": ev["source"], "evidence": read_lines(workdir, ev["path"], start, end, pad=2),
            "obligation_id": sorted(state["obligations"],
                                    key=lambda o: severity_rank(o["severity"]))[0]["id"],
            "citations": [{"obligation_id": o["id"], "regulation": o["regulation"],
                           "section_ref": o["section_ref"], "source_url": o["source_url"],
                           "retrieved_at": o["retrieved_at"], "quote": o["quote"]}
                          for o in sorted(state["obligations"],
                                          key=lambda o: severity_rank(o["severity"]))],
        })
    return {"findings": findings, "errors": errors}


# --- 4. Aggregate, alert, approve ---------------------------------------------------------


def _fingerprint(org_id: str, f: dict) -> str:
    """Stable across runs: based on the flagged code text, not the line number."""
    first = next((ln.split(" | ", 1)[-1].strip() for ln in f["evidence"].splitlines()
                  if ln.strip().startswith(str(f["start_line"]))), f["path"])
    return hashlib.sha256(f"{org_id}|{f['category']}|{f['path']}|{first}".encode()).hexdigest()


def aggregate(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    merged: dict[tuple, dict] = {}
    for f in state.get("findings", []):
        key = (f["category"], f["path"], f["start_line"])
        if key not in merged or (f["status"] == "violation", f["confidence"]) > (
                merged[key]["status"] == "violation", merged[key]["confidence"]):
            merged[key] = f
    findings = sorted(merged.values(), key=lambda f: (severity_rank(f["severity"]),
                                                      f["status"] != "violation", f["path"]))
    with _db(runtime) as s:
        run = s.get(AuditRun, uuid.UUID(state["run_id"]))
        org = s.get(Organization, run.org_id)
        threshold = severity_rank(org.alert_min_severity)
        for f in findings:
            f["fingerprint"] = _fingerprint(state["org_id"], f)
            s.add(Finding(org_id=run.org_id, run_id=run.id,
                          obligation_id=uuid.UUID(f["obligation_id"]), path=f["path"],
                          start_line=f["start_line"], end_line=f["end_line"],
                          severity=f["severity"], status=f["status"], category=f["category"],
                          rule_id=f["rule_id"], evidence=f["evidence"], reasoning=f["reasoning"],
                          confidence=f["confidence"], fingerprint=f["fingerprint"],
                          citations=f["citations"]))
        meter = ctx.engine.meter
        run.input_tokens, run.output_tokens = meter.input_tokens, meter.output_tokens
        run.cost_usd = meter.cost(ctx.settings)
        counts: dict[str, int] = defaultdict(int)
        for f in findings:
            counts[f["status"]] += 1
        run.stats = {"obligations": len(state.get("obligations", [])),
                     "static_hits": len(state.get("static_hits", [])),
                     "findings": dict(counts), "llm_calls": meter.calls,
                     "errors": state.get("errors", [])}
    alertable = sum(1 for f in findings if f["status"] == "violation"
                    and severity_rank(f["severity"]) <= threshold)
    return {"findings": [], "alertable": alertable}


def route_after_aggregate(state: AuditState) -> str:
    return "notify" if state.get("alertable") else "approval"


def notify(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    with _db(runtime) as s:
        run = s.get(AuditRun, uuid.UUID(state["run_id"]))
        org = s.get(Organization, run.org_id)
        repo = s.get(Repo, run.repo_id)
        threshold = severity_rank(org.alert_min_severity)
        rows = list(s.scalars(select(Finding).where(Finding.run_id == run.id,
                                                    Finding.status == "violation")))
        already = set(s.scalars(select(AlertLog.fingerprint).where(AlertLog.org_id == org.id)))
        fresh = [f for f in rows if severity_rank(f.severity) <= threshold
                 and f.fingerprint not in already]
        if not fresh:
            return {}
        alert = Alert(org_name=org.name, repo_name=repo.name, run_id=str(run.id),
                      commit=run.commit or "", dashboard_url=runtime.context.settings.dashboard_url,
                      findings=[{"severity": f.severity, "category": f.category, "path": f.path,
                                 "start_line": f.start_line,
                                 "citation": f"{f.citations[0]['section_ref']}" if f.citations else "",
                                 "label": CATEGORIES[f.category].label} for f in fresh])
        channels = runtime.context.notifier.send(alert, org.slack_webhook_url,
                                                 list(org.alert_emails.get("to", [])))
        for f in fresh:
            s.add(AlertLog(org_id=org.id, fingerprint=f.fingerprint, run_id=run.id,
                           channels=",".join(channels)))
    return {}


def approval(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    if not runtime.context.settings.require_approval:
        return {"approval": {"approved": True, "approved_by": None, "approved_by_name": None}}
    _set_status(runtime, state["run_id"], status="awaiting_approval")
    decision = interrupt({"run_id": state["run_id"],
                          "message": "Approve this audit before the report is generated."})
    if not decision.get("approved"):
        _set_status(runtime, state["run_id"], status="rejected", finished_at=datetime.now(UTC))
    return {"approval": decision}


def route_after_approval(state: AuditState) -> str:
    return "generate_report" if (state.get("approval") or {}).get("approved") else "__end__"


def generate_report(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    from sentinel.report.render import build_report

    approval_info = state.get("approval") or {}
    with _db(runtime) as s:
        report = build_report(s, uuid.UUID(state["run_id"]), runtime.context.storage,
                              approved_by=approval_info.get("approved_by"),
                              approved_by_name=approval_info.get("approved_by_name"))
        run = s.get(AuditRun, uuid.UUID(state["run_id"]))
        run.status, run.finished_at = "completed", datetime.now(UTC)
        return {"report_id": str(report.id)}
