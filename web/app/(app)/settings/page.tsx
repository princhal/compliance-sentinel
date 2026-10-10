import { saveSettings } from "@/app/actions";
import { api, roles } from "@/lib/api";
import type { OrgSettings } from "@/lib/types";

export default async function SettingsPage() {
  const [settings, { isAdmin }] = await Promise.all([api<OrgSettings>("/org/settings"), roles()]);
  return (
    <>
      <h1>Alert settings</h1>
      {!isAdmin && <p className="muted">Only admins can change these settings.</p>}
      <form action={saveSettings} className="card stack">
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
          <input name="alert_emails" defaultValue={settings.alert_emails.join(", ")} disabled={!isAdmin} />
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
        {isAdmin && <button className="primary" type="submit">Save</button>}
      </form>
    </>
  );
}
