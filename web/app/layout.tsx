import type { Metadata } from "next";
import Link from "next/link";
import { ClerkProvider, OrganizationSwitcher, Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Compliance Sentinel", template: "%s · Compliance Sentinel" },
  description: "Audits your codebase against new regulations and produces audit-ready reports.",
};

// Clerk's components read the same tokens as the rest of the app, so they follow light and dark mode.
const clerkAppearance = {
  variables: {
    colorBackground: "var(--surface)",
    colorForeground: "var(--ink)",
    colorMutedForeground: "var(--muted)",
    colorPrimary: "var(--accent)",
    colorPrimaryForeground: "var(--accent-ink)",
    colorInput: "var(--surface)",
    colorInputForeground: "var(--ink)",
    colorBorder: "var(--line)",
    colorNeutral: "var(--ink)",
    colorDanger: "var(--critical)",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ClerkProvider appearance={clerkAppearance}>
          <header className="top">
            <Link href="/" className="brand">Compliance Sentinel</Link>
            <Show when="signed-in">
              <nav>
                <Link href="/runs">Runs</Link>
                <Link href="/repos">Repos</Link>
                <Link href="/regulations">Regulations</Link>
                <Link href="/settings">Settings</Link>
              </nav>
              {/* Clerk mounts these client-side; the slots hold their size so the header doesn't jump. */}
              <div className="clerk-slot slot-org">
                <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/runs" />
              </div>
              <div className="clerk-slot slot-user">
                <UserButton />
              </div>
            </Show>
            <Show when="signed-out">
              <nav />
              <SignInButton />
              <SignUpButton />
            </Show>
          </header>
          <main>{children}</main>
        </ClerkProvider>
      </body>
    </html>
  );
}
