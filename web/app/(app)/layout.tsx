import { auth } from "@clerk/nextjs/server";
import { OrganizationList } from "@clerk/nextjs";

/** Every page in this group needs an active organization: all data is org-scoped. */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, orgId, redirectToSignIn } = await auth();
  if (!isAuthenticated) return redirectToSignIn();
  if (!orgId) {
    return (
      <div className="card">
        <h1>Choose an organization</h1>
        <p className="muted">Repos, audits and reports belong to an organization. Pick one or create one.</p>
        {/* A list rather than a second switcher: the header already has one, and two identical
            "Open organization switcher" buttons are ambiguous to screen readers. */}
        <OrganizationList hidePersonal afterSelectOrganizationUrl="/runs" afterCreateOrganizationUrl="/runs" />
      </div>
    );
  }
  return <>{children}</>;
}
