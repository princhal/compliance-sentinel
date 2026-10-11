import type { Metadata } from "next";
import Link from "next/link";
import { ClerkProvider, OrganizationSwitcher, Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";

import "./globals.css";

export const metadata: Metadata = {
  title: "Compliance Sentinel",
  description: "Audits your codebase against new regulations and produces audit-ready reports.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ClerkProvider>
          <header className="top">
            <Link href="/" className="brand">Compliance Sentinel</Link>
            <Show when="signed-in">
              <nav>
                <Link href="/runs">Runs</Link>
                <Link href="/repos">Repos</Link>
                <Link href="/regulations">Regulations</Link>
                <Link href="/settings">Settings</Link>
              </nav>
              <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/runs" />
              <UserButton />
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
