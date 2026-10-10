import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import Link from "next/link";

export default async function Home() {
  const { isAuthenticated } = await auth();
  if (isAuthenticated) redirect("/runs");
  return (
    <section className="hero">
      <h1>Know when new rules break your code.</h1>
      <p className="muted">
        Compliance Sentinel watches regulatory sources every day, audits your repositories against new
        and changed obligations, and produces an audit-ready PDF with a citation for every finding.
      </p>
      <p><Link className="button primary" href="/sign-in">Sign in</Link></p>
    </section>
  );
}
