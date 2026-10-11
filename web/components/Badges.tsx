export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge sev-${severity}`}>{severity}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge st-${status}`}>{status.replaceAll("_", " ")}</span>;
}

// Month names, never numbers: "11/10/2026" reads as 11 October or 10 November depending on the reader.
export function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "–";
}

export function formatDay(value: string | null): string {
  return value ? new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "–";
}
