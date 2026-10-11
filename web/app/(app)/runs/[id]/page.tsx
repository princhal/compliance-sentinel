import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { decideRun, reviewFinding } from "@/app/actions";
import { formatDate, SeverityBadge, StatusBadge } from "@/components/Badges";
import { api, isNotFound, roles } from "@/lib/api";
import type { Finding, Run } from "@/lib/types";

export const metadata: Metadata = { title: "Audit run" };

const REVIEW_OPTIONS = ["open", "accepted_risk", "false_positive", "fixed"] as const;

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [run, findings, { canApprove }] = await Promise.all([
    api<Run>(`/runs/${encodeURIComponent(id)}`),
    api<Finding[]>(`/findings?run_id=${encodeURIComponent(id)}`),
    roles(),
  ]).catch((err) => {
    if (isNotFound(err)) notFound();
    throw err;
  });
  const violations = findings.filter((f) => f.status === "violation");
  const reviews = findings.filter((f) => f.status === "needs_review");
  return (
    <>
      <h1>{run.repo_name} <StatusBadge status={run.status} /></h1>
      <p className="muted">
        Commit {run.commit?.slice(0, 12) ?? "–"} · {run.trigger.replaceAll("_", " ")} · started {formatDate(run.started_at)} ·
        engine {run.engine || "–"}
      </p>
      <div className="grid">
        <div className="card kpi"><b>{violations.length}</b>Violations</div>
        <div className="card kpi"><b>{reviews.length}</b>Need review</div>
        <div className="card kpi"><b>{run.stats.obligations ?? 0}</b>Obligations checked</div>
        <div className="card kpi"><b>${run.cost_usd.toFixed(2)}</b>{run.input_tokens + run.output_tokens} tokens</div>
      </div>

      {run.status === "awaiting_approval" && (
        <div className="card" style={{ marginTop: 16 }}>
          <b>This audit is waiting for approval.</b>
          <p className="muted">Approving generates the PDF report with your name in the signature block.</p>
          {canApprove ? (
            <form action={decideRun} className="inline">
              <input type="hidden" name="run_id" value={run.id} />
              <button className="primary" name="decision" value="approve">Approve and generate report</button>
              <button className="danger" name="decision" value="reject">Reject</button>
            </form>
          ) : (
            <p className="muted">Only auditors and admins can approve.</p>
          )}
        </div>
      )}
      {run.report && (
        <div className="card row" style={{ marginTop: 16 }}>
          <a className="button primary" href={`/api/reports/${run.report.id}`}>Download PDF report</a>
          <span className="muted">
            Approved by {run.report.approved_by_name ?? "–"} · SHA-256 {run.report.sha256.slice(0, 16)}…
          </span>
        </div>
      )}
      {run.error && <pre>{run.error}</pre>}

      <h2>Findings</h2>
      {findings.length === 0 && <p className="muted">No findings.</p>}
      {findings.map((f) => (
        <div key={f.id} className="card finding">
          <div className="row">
            <SeverityBadge severity={f.severity} />
            <b>{f.label}</b>
            <span className="muted">{f.status.replaceAll("_", " ")} · {Math.round(f.confidence * 100)}% · {f.rule_id}</span>
          </div>
          <code>{f.path}:{f.start_line}</code>
          <pre>{f.evidence}</pre>
          <p>{f.reasoning}</p>
          {f.citations.slice(0, 2).map((c) => (
            <blockquote key={c.obligation_id}>
              <b>{c.section_ref}</b>: “{c.quote.length > 300 ? `${c.quote.slice(0, 300)}…` : c.quote}”{" "}
              <a href={c.source_url} target="_blank" rel="noreferrer">source</a>
            </blockquote>
          ))}
          {canApprove && (
            <form action={reviewFinding} className="inline">
              <input type="hidden" name="finding_id" value={f.id} />
              <input type="hidden" name="run_id" value={run.id} />
              <select name="review_status" defaultValue={f.review_status} aria-label="Review status">
                {REVIEW_OPTIONS.map((o) => <option key={o} value={o}>{o.replaceAll("_", " ")}</option>)}
              </select>
              <button type="submit">Save</button>
            </form>
          )}
        </div>
      ))}
    </>
  );
}
