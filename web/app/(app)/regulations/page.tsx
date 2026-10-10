import { SeverityBadge } from "@/components/Badges";
import { api } from "@/lib/api";
import type { Obligation, Regulation } from "@/lib/types";

export default async function RegulationsPage() {
  const [docs, obligations] = await Promise.all([
    api<Regulation[]>("/regulations"),
    api<Obligation[]>("/obligations"),
  ]);
  return (
    <>
      <h1>Regulations</h1>
      <p className="muted">Shared by every organization. Checked daily for new rules and amendments.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Regulation</th><th>Document</th><th>Version</th><th>Retrieved</th></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td>{d.regulation}</td>
                <td><a href={d.url} target="_blank" rel="noreferrer">{d.title}</a></td>
                <td>v{d.version}</td>
                <td>{new Date(d.fetched_at).toLocaleDateString("en-GB")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Obligations ({obligations.length})</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Section</th><th>Category</th><th>Severity</th><th>Duty</th></tr></thead>
          <tbody>
            {obligations.map((o) => (
              <tr key={o.id}>
                <td>{o.section_ref}</td><td>{o.category.replaceAll("_", " ")}</td>
                <td><SeverityBadge severity={o.severity} /></td>
                <td className="muted">{o.quote.length > 220 ? `${o.quote.slice(0, 220)}…` : o.quote}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
