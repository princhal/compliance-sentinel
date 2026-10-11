"use client";

import Link from "next/link";
import { useEffect } from "react";

/** Keeps the header, nav and org switcher on screen when a page's API call fails. */
export default function AppError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <>
      <title>Something went wrong · Compliance Sentinel</title>
      <div className="card stack" role="alert">
        <h1>This page couldn&apos;t load</h1>
        <p className="muted">
          The Compliance Sentinel API returned an error or could not be reached. Try again, or go back to your runs.
        </p>
        {/* Production builds replace server error messages with a generic one, so only show it in development. */}
        {process.env.NODE_ENV === "development" && <pre>{error.message}</pre>}
        {error.digest && <p className="muted">Reference: {error.digest}</p>}
        <div className="row">
          <button className="primary" type="button" onClick={() => retry()}>Try again</button>
          <Link className="button" href="/runs">Go to runs</Link>
        </div>
      </div>
    </>
  );
}
