import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Page not found" };

/** Rendered inside the root layout, so the app header and theme stay in place. */
export default function NotFound() {
  return (
    <div className="card stack">
      <h1>Page not found</h1>
      <p className="muted">There is nothing at this address. It may have moved, or the link may be wrong.</p>
      <div className="row">
        <Link className="button primary" href="/runs">Go to runs</Link>
      </div>
    </div>
  );
}
