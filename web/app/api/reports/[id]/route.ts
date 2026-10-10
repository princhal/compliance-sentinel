import { apiRaw } from "@/lib/api";

/** Streams a report PDF from the API, so the browser never needs the API's address or a token. */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await apiRaw(`/reports/${encodeURIComponent(id)}/pdf`);
  if (!res.ok) return new Response("Report not found", { status: res.status });
  return new Response(res.body, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": res.headers.get("content-disposition") ?? "attachment",
      "X-Content-SHA256": res.headers.get("x-content-sha256") ?? "",
    },
  });
}
