import type { Metadata } from "next";
import Link from "next/link";

import { triggerRun } from "@/app/actions";
import { formatDate, StatusBadge } from "@/components/Badges";
import { api, roles } from "@/lib/api";
import type { Repo, Run } from "@/lib/types";

export const metadata: Metadata = { title: "Audit runs" };

export default async function RunsPage() {
  const [runs, repos, { isAdmin }] = await Promise.all([
    api<Run[]>("/runs"),
    api<Repo[]>("/repos"),
    roles(),
  ]);
  return (
    <>
      <h1>Audit runs</h1>
      {isAdmin && repos.length > 0 && (
        <div className="card row">
          <span className="muted">Run an audit now:</span>
          {repos.map((r) => (
            <form key={r.id} action={triggerRun} className="inline">
              <input type="hidden" name="repo_id" value={r.id} />
              <button className="primary" type="submit">{r.name}</button>
            </form>
          ))}
        </div>
      )}
      <h2>History</h2>
      {runs.length === 0 ? (
        <p className="muted">No runs yet. {isAdmin ? <Link href="/repos">Add a repo</Link> : null}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Started</th><th>Repo</th><th>Trigger</th><th>Status</th><th>Violations</th><th>Review</th><th>Cost</th></tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td><Link href={`/runs/${run.id}`}>{formatDate(run.created_at)}</Link></td>
                  <td>{run.repo_name}<div className="muted">{run.commit?.slice(0, 12)}</div></td>
                  <td>{run.trigger.replaceAll("_", " ")}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{run.stats.findings?.violation ?? 0}</td>
                  <td>{run.stats.findings?.needs_review ?? 0}</td>
                  <td>${run.cost_usd.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
