import type { Metadata } from "next";

import { addRepo, deleteRepo } from "@/app/actions";
import { formatDate } from "@/components/Badges";
import { api, roles } from "@/lib/api";
import type { Repo } from "@/lib/types";

export const metadata: Metadata = { title: "Repositories" };

export default async function ReposPage() {
  const [repos, { isAdmin }] = await Promise.all([api<Repo[]>("/repos"), roles()]);
  return (
    <>
      <h1>Repositories</h1>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>URL</th><th>Last commit</th><th>Indexed</th><th /></tr></thead>
          <tbody>
            {repos.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td><td className="muted">{r.url}</td>
                <td>{r.last_commit?.slice(0, 12) ?? "–"}</td><td>{formatDate(r.last_indexed_at)}</td>
                <td>
                  {isAdmin && (
                    <form action={deleteRepo}>
                      <input type="hidden" name="repo_id" value={r.id} />
                      <button className="danger" type="submit">Remove</button>
                    </form>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {isAdmin && (
        <>
          <h2>Add a repository</h2>
          <form action={addRepo} className="card stack">
            <label>Name<input name="name" required placeholder="checkout-service" /></label>
            <label>Git URL<input name="url" required placeholder="https://github.com/acme/checkout.git" /></label>
            <label>Branch<input name="default_branch" placeholder="main" /></label>
            <button className="primary" type="submit">Add repository</button>
          </form>
        </>
      )}
    </>
  );
}
