import type { Metadata } from "next";

import { SettingsForm } from "@/components/SettingsForm";
import { api, roles } from "@/lib/api";
import type { OrgSettings } from "@/lib/types";

export const metadata: Metadata = { title: "Alert settings" };

export default async function SettingsPage() {
  const [settings, { isAdmin }] = await Promise.all([api<OrgSettings>("/org/settings"), roles()]);
  return (
    <>
      <h1>Alert settings</h1>
      {!isAdmin && <p className="muted">Only admins can change these settings.</p>}
      <SettingsForm settings={settings} isAdmin={isAdmin} />
    </>
  );
}
