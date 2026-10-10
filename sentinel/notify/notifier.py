"""Slack and email alerts for critical findings."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from sentinel.config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class Alert:
    org_name: str
    repo_name: str
    run_id: str
    commit: str
    findings: list[dict[str, Any]]  # each: severity, category, path, start_line, citation, reasoning
    dashboard_url: str
    pdf: bytes | None = None


def slack_blocks(alert: Alert) -> dict[str, Any]:
    top = sorted(alert.findings, key=lambda f: f["severity"] != "critical")[:3]
    lines = "\n".join(
        f"• *{f['severity'].upper()}* `{f['path']}:{f['start_line']}` {f['citation']}: "
        f"{f['label']}" for f in top)
    more = len(alert.findings) - len(top)
    return {
        "text": f"Compliance Sentinel: {len(alert.findings)} violations in {alert.repo_name}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text",
                                        "text": f"🚨 {len(alert.findings)} compliance violations"}},
            {"type": "section", "text": {"type": "mrkdwn", "text":
                f"*Repo:* {alert.repo_name} @ `{alert.commit[:12]}`\n*Org:* {alert.org_name}"}},
            {"type": "section", "text": {"type": "mrkdwn",
                                         "text": lines + (f"\n…and {more} more" if more else "")}},
            {"type": "actions", "elements": [{"type": "button", "style": "danger",
                "text": {"type": "plain_text", "text": "Review findings"},
                "url": f"{alert.dashboard_url}/runs/{alert.run_id}"}]},
        ],
    }


class Notifier:
    def __init__(self, settings: Settings | None = None,
                 client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.http = client or httpx.Client(timeout=15)

    def send(self, alert: Alert, slack_webhook_url: str | None, emails: list[str]) -> list[str]:
        sent: list[str] = []
        if slack_webhook_url:
            try:
                self.http.post(slack_webhook_url, json=slack_blocks(alert)).raise_for_status()
                sent.append("slack")
            except httpx.HTTPError as exc:
                log.warning("Slack alert failed: %s", exc)
        if emails and self.settings.resend_api_key:
            try:
                self._email(alert, emails)
                sent.append("email")
            except httpx.HTTPError as exc:
                log.warning("Email alert failed: %s", exc)
        if not sent:
            log.warning("ALERT (no channel configured) %s: %s violations in %s", alert.org_name,
                        len(alert.findings), alert.repo_name)
            sent.append("log")
        return sent

    def _email(self, alert: Alert, emails: list[str]) -> None:
        rows = "".join(
            f"<li><b>{f['severity'].upper()}</b> <code>{f['path']}:{f['start_line']}</code> "
            f"{f['citation']}: {f['label']}</li>" for f in alert.findings[:20])
        payload: dict[str, Any] = {
            "from": self.settings.alert_from_email, "to": emails,
            "subject": f"[Compliance Sentinel] {len(alert.findings)} violations in {alert.repo_name}",
            "html": f"<p>Commit <code>{alert.commit[:12]}</code></p><ul>{rows}</ul>"
                    f"<p><a href='{alert.dashboard_url}/runs/{alert.run_id}'>Review findings</a></p>",
        }
        if alert.pdf:
            payload["attachments"] = [{"filename": f"compliance-report-{alert.run_id[:8]}.pdf",
                                       "content": base64.b64encode(alert.pdf).decode()}]
        self.http.post("https://api.resend.com/emails", json=payload,
                       headers={"Authorization": f"Bearer {self.settings.resend_api_key}"}
                       ).raise_for_status()
