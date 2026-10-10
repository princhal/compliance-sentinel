"use server";

import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";

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

export async function saveSettings(formData: FormData) {
  const emails = String(formData.get("alert_emails") ?? "")
    .split(/[\s,]+/)
    .filter(Boolean);
  const slack = String(formData.get("slack_webhook_url") ?? "").trim();
  const clearSlack = formData.get("clear_slack") === "on";
  await api("/org/settings", {
    method: "PUT",
    body: JSON.stringify({
      slack_webhook_url: slack || null,
      clear_slack: clearSlack,
      alert_emails: emails,
      alert_min_severity: formData.get("alert_min_severity"),
    }),
  });
  revalidatePath("/settings");
}
