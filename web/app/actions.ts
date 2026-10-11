"use server";

import { revalidatePath } from "next/cache";

import { api, ApiError } from "@/lib/api";

export async function triggerRun(formData: FormData) {
  await api("/runs", { method: "POST", body: JSON.stringify({ repo_id: formData.get("repo_id") }) });
  revalidatePath("/runs");
}

export async function decideRun(formData: FormData) {
  const id = String(formData.get("run_id"));
  await api(`/runs/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved: formData.get("decision") === "approve" }),
  });
  revalidatePath(`/runs/${id}`);
}

export async function reviewFinding(formData: FormData) {
  await api(`/findings/${formData.get("finding_id")}`, {
    method: "PATCH",
    body: JSON.stringify({ review_status: formData.get("review_status") }),
  });
  revalidatePath(`/runs/${formData.get("run_id")}`);
}

export async function addRepo(formData: FormData) {
  await api("/repos", {
    method: "POST",
    body: JSON.stringify({
      name: formData.get("name"),
      url: formData.get("url"),
      default_branch: formData.get("default_branch") || "main",
    }),
  });
  revalidatePath("/repos");
}

export async function deleteRepo(formData: FormData) {
  await api(`/repos/${formData.get("repo_id")}`, { method: "DELETE" });
  revalidatePath("/repos");
}

export type SettingsState = { status: "idle" | "saved" | "error"; message?: string };

// Deliberately loose (something@something.tld): the API's EmailStr check is the strict one.
const EMAIL = /^[^\s@,]+@[^\s@,]+\.[^\s@,]+$/;

export async function saveSettings(_prev: SettingsState, formData: FormData): Promise<SettingsState> {
  const emails = String(formData.get("alert_emails") ?? "")
    .split(/[\s,]+/)
    .filter(Boolean);
  const invalid = emails.filter((e) => !EMAIL.test(e));
  if (invalid.length) {
    return { status: "error", message: `Not a valid email address: ${invalid.join(", ")}` };
  }
  const slack = String(formData.get("slack_webhook_url") ?? "").trim();
  const clearSlack = formData.get("clear_slack") === "on";
  try {
    await api("/org/settings", {
      method: "PUT",
      body: JSON.stringify({
        slack_webhook_url: slack || null,
        clear_slack: clearSlack,
        alert_emails: emails,
        alert_min_severity: formData.get("alert_min_severity"),
      }),
    });
  } catch (err) {
    // 422 means the API's stricter validation rejected a field; anything else is unexpected.
    if (err instanceof ApiError && err.status === 422) {
      return { status: "error", message: "Some settings were not accepted. Check the email addresses and Slack URL." };
    }
    throw err;
  }
  revalidatePath("/settings");
  return { status: "saved", message: "Settings saved." };
}
