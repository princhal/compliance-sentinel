"""Score an audit run against evals/golden.yaml, and retrieval against evals/rag_questions.yaml.

Run with: sentinel eval   (scores the latest completed run of the demo repo)
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select

from sentinel.db.models import AuditRun, Finding, Obligation, RegChunk, Repo
from sentinel.db.session import session_scope
from sentinel.embeddings import get_embedder
from sentinel.rag.retriever import search_regulations

ROOT = Path(__file__).resolve().parent.parent
LINE_SLACK = 0  # Look-alike decoys sit on neighbouring lines, so matching is exact.


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def load_labels(golden_path: Path = ROOT / "evals" / "golden.yaml") -> dict:
    golden = yaml.safe_load(golden_path.read_text())
    repo_dir = ROOT / golden["repo"]
    for group in ("violations", "decoys"):
        for item in golden[group]:
            if "match" in item:
                lines = (repo_dir / item["path"]).read_text().splitlines()
                item["line"] = next(i for i, ln in enumerate(lines, 1) if item["match"] in ln)
    return golden


def _matches(f: dict, label: dict) -> bool:
    return (f["path"] == label["path"] and f["category"] == label["category"]
            and f["start_line"] - LINE_SLACK <= label["line"] <= f["end_line"] + LINE_SLACK)


def score_findings(findings: list[dict], golden: dict) -> dict:
    violations, decoys = golden["violations"], golden["decoys"]
    confirmed = [f for f in findings if f["status"] == "violation"]
    flagged = [f for f in findings if f["status"] in ("violation", "needs_review")]

    def caught(label, pool):
        return any(_matches(f, label) for f in pool)

    tp = [v for v in violations if caught(v, confirmed)]
    fp = [f for f in confirmed if not any(_matches(f, v) for v in violations)]
    precision = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 0.0
    recall = len(tp) / len(violations) if violations else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    by_diff = {}
    for diff in sorted({v.get("difficulty", "easy") for v in violations}):
        group = [v for v in violations if v.get("difficulty", "easy") == diff]
        by_diff[diff] = {"labels": len(group),
                         "recall_confirmed": round(sum(caught(v, confirmed) for v in group) / len(group), 3),
                         "recall_flagged": round(sum(caught(v, flagged) for v in group) / len(group), 3)}
    return {
        "violations_labeled": len(violations), "decoys_labeled": len(decoys),
        "confirmed_findings": len(confirmed), "needs_review_findings": len(flagged) - len(confirmed),
        "true_positives": len(tp), "false_positives": len(fp),
        "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
        "recall_including_needs_review": round(sum(caught(v, flagged) for v in violations)
                                               / len(violations), 3),
        "decoy_false_alarms": [d["id"] for d in decoys if caught(d, confirmed)],
        "by_difficulty": by_diff,
        "missed": [v["id"] for v in violations if not caught(v, flagged)],
        "false_positive_locations": [f"{f['path']}:{f['start_line']} ({f['category']})" for f in fp],
    }


def citation_accuracy(session, findings: list[Finding]) -> dict:
    """A citation is supported when its quote appears in the stored regulation text and its
    obligation category matches the finding's category."""
    checked = supported = 0
    for f in findings:
        for c in f.citations:
            ob = session.get(Obligation, uuid.UUID(c["obligation_id"]))
            chunk = session.get(RegChunk, ob.chunk_id) if ob else None
            checked += 1
            if ob and chunk and ob.category == f.category and \
                    _norm(c["quote"])[:120] in _norm(f"{chunk.context} {chunk.text}"):
                supported += 1
    return {"citations_checked": checked,
            "citation_accuracy": round(supported / checked, 3) if checked else None}


def score_retrieval(session, k: int = 5) -> dict:
    qs = yaml.safe_load((ROOT / "evals" / "rag_questions.yaml").read_text())["questions"]
    embedder = get_embedder()
    hits_at_k = 0
    rr_total = 0.0
    misses = []
    for item in qs:
        refs = [h.row.section_ref for h in search_regulations(session, embedder, item["q"], k=k)]
        rank = next((i for i, r in enumerate(refs, 1) if r in item["expected"]), None)
        if rank:
            hits_at_k += 1
            rr_total += 1 / rank
        else:
            misses.append(item["q"])
    return {"embedder": embedder.name, "k": k, "questions": len(qs),
            f"recall_at_{k}": round(hits_at_k / len(qs), 3), "mrr": round(rr_total / len(qs), 3),
            "missed_questions": misses}


def main(run_id: str | None, out: Path) -> dict:
    golden = load_labels()
    with session_scope() as s:
        if run_id:
            run = s.get(AuditRun, uuid.UUID(run_id))
        else:
            run = s.scalar(select(AuditRun).join(Repo).where(
                Repo.name == "shopwise-demo", AuditRun.status == "completed")
                .order_by(AuditRun.created_at.desc()).limit(1))
        rows = list(s.scalars(select(Finding).where(Finding.run_id == run.id)))
        findings = [{"path": f.path, "category": f.category, "start_line": f.start_line,
                     "end_line": f.end_line, "status": f.status} for f in rows]
        result = {
            "run_id": str(run.id), "engine": run.llm_engine,
            "findings": score_findings(findings, golden),
            "citations": citation_accuracy(s, rows),
            "retrieval": score_retrieval(s),
            "cost": {"input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
                     "usd": run.cost_usd,
                     "seconds": round((run.finished_at - run.started_at).total_seconds(), 1)
                     if run.finished_at and run.started_at else None},
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result
