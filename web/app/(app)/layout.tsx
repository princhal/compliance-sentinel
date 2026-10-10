import { auth } from "@clerk/nextjs/server";
import { OrganizationSwitcher } from "@clerk/nextjs";

/** Every page in this group needs an active organization: all data is org-scoped. */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, orgId, redirectToSignIn } = await auth();
  if (!isAuthenticated) return redirectToSignIn();
  if (!orgId) {
    return (
      <div className="card">
        <h1>Choose an organization</h1>
        <p className="muted">Repos, audits and reports belong to an organization. Pick one or create one.</p>
        <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/runs" />
      </div>
    );
  }
  return <>{children}</>;
}
