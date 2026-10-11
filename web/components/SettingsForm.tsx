"use client";

import { useActionState, useState } from "react";

import { saveSettings, type SettingsState } from "@/app/actions";
import type { OrgSettings } from "@/lib/types";

export function SettingsForm({ settings, isAdmin }: { settings: OrgSettings; isAdmin: boolean }) {
  const [state, formAction, pending] = useActionState<SettingsState, FormData>(saveSettings, { status: "idle" });
  // Controlled, so a rejected list stays in the field for correction instead of being reset.
  const [emails, setEmails] = useState(settings.alert_emails.join(", "));
  const emailError = state.status === "error";

  return (
    <form action={formAction} className="card stack">
      <label>
        Slack incoming webhook URL
        <input name="slack_webhook_url" type="url" disabled={!isAdmin}
          placeholder={settings.slack_webhook_configured ? "Configured. Leave blank to keep it." : "https://hooks.slack.com/services/…"} />
      </label>
      <label>
        <span><input type="checkbox" name="clear_slack" disabled={!isAdmin} /> Remove the Slack webhook</span>
      </label>
      <label>
        Alert emails (comma separated)
        {/* type="email" multiple makes the browser check each comma-separated address before submitting. */}
        <input name="alert_emails" type="email" multiple value={emails} onChange={(e) => setEmails(e.target.value)}
          disabled={!isAdmin} placeholder="legal@example.com, security@example.com"
          aria-invalid={emailError || undefined} aria-describedby={emailError ? "settings-error" : undefined} />
      </label>
      <label>
        Alert when a violation is at least
        <select name="alert_min_severity" defaultValue={settings.alert_min_severity} disabled={!isAdmin}>
          <option value="critical">critical</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
      </label>
      {state.status === "error" && <p id="settings-error" className="error" role="alert">{state.message}</p>}
      {state.status === "saved" && <p className="success" role="status">{state.message}</p>}
      {isAdmin && <button className="primary" type="submit" disabled={pending}>{pending ? "Saving…" : "Save"}</button>}
    </form>
  );
}
