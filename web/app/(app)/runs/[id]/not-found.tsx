import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Run not found" };

export default function RunNotFound() {
  return (
    <div className="card stack">
      <h1>Run not found</h1>
      <p className="muted">
        This audit run doesn&apos;t exist, or it belongs to a different organization than the one selected.
      </p>
      <div className="row">
        <Link className="button primary" href="/runs">Back to runs</Link>
      </div>
    </div>
  );
}
