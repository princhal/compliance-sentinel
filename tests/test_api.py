"""API tests: tenant isolation and role checks (dev auth headers stand in for Clerk tokens)."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db


def hdr(org: str, role: str = "admin", user: str | None = None) -> dict[str, str]:
    return {"x-dev-org": org, "x-dev-role": role, "x-dev-user": user or f"user_{org}_{role}"}


@pytest.fixture(scope="module")
def client(ingested):
    from sentinel.api.app import app

    return TestClient(app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_orgs_cannot_see_each_others_data(client, tmp_path):
    from sentinel.seed import DEMO_REPO

    a, b = hdr("org_alpha"), hdr("org_beta")
    repo = client.post("/repos", json={"name": "alpha-app", "url": str(DEMO_REPO)}, headers=a)
    assert repo.status_code == 201
    repo_id = repo.json()["id"]
    assert [r["name"] for r in client.get("/repos", headers=b).json()] == []
    assert client.post("/runs", json={"repo_id": repo_id}, headers=b).status_code == 404

    run = client.post("/runs", json={"repo_id": repo_id}, headers=a).json()
    for _ in range(60):
        status = client.get(f"/runs/{run['id']}", headers=a).json()["status"]
        if status in ("awaiting_approval", "failed"):
            break
        time.sleep(0.5)
    assert status == "awaiting_approval"

    assert client.get(f"/runs/{run['id']}", headers=b).status_code == 404
    assert client.get("/findings", params={"run_id": run["id"]}, headers=b).json() == []
    assert client.post(f"/runs/{run['id']}/approve", json={"approved": True},
                       headers=hdr("org_beta", "admin")).status_code == 404

    # A member of the right org still cannot approve; an auditor can.
    member = hdr("org_alpha", "member")
    assert client.post(f"/runs/{run['id']}/approve", json={"approved": True},
                       headers=member).status_code == 403
    ok = client.post(f"/runs/{run['id']}/approve", json={"approved": True},
                     headers=hdr("org_alpha", "auditor", "user_ada"))
    assert ok.status_code == 202
    for _ in range(60):
        detail = client.get(f"/runs/{run['id']}", headers=a).json()
        if detail["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert detail["status"] == "completed", detail.get("error")
    report_id = detail["report"]["id"]
    pdf = client.get(f"/reports/{report_id}/pdf", headers=a)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["x-content-sha256"] == detail["report"]["sha256"]
    assert client.get(f"/reports/{report_id}/pdf", headers=b).status_code == 404

    findings = client.get("/findings", params={"run_id": run["id"]}, headers=a).json()
    assert findings and all(f["citations"] for f in findings)
    fid = findings[0]["id"]
    assert client.patch(f"/findings/{fid}", json={"review_status": "accepted_risk"},
                        headers=b).status_code == 404
    reviewed = client.patch(f"/findings/{fid}", json={"review_status": "accepted_risk"},
                            headers=hdr("org_alpha", "auditor", "user_ada"))
    assert reviewed.json()["review_status"] == "accepted_risk"


def test_members_cannot_manage_repos_or_settings(client):
    m = hdr("org_gamma", "member")
    assert client.post("/repos", json={"name": "x", "url": "https://x.test/r.git"},
                       headers=m).status_code == 403
    assert client.put("/org/settings", json={"alert_min_severity": "high"},
                      headers=m).status_code == 403
    ok = client.put("/org/settings", json={"alert_min_severity": "high",
                                           "alert_emails": ["legal@acme-legal.com"]},
                    headers=hdr("org_gamma"))
    assert ok.json()["alert_min_severity"] == "high"
    g = hdr("org_gamma")
    set_hook = {"slack_webhook_url": "https://hooks.slack.com/services/T/B/x"}
    assert client.put("/org/settings", json=set_hook, headers=g).json()["slack_webhook_configured"]
    assert client.put("/org/settings", json={}, headers=g).json()["slack_webhook_configured"]
    cleared = client.put("/org/settings", json={"clear_slack": True}, headers=g).json()
    assert cleared["slack_webhook_configured"] is False


def test_internal_scrape_requires_token(client):
    assert client.post("/internal/scrape", headers={"x-internal-token": "nope"}).status_code == 401


def test_clerk_webhook_signature_and_idempotency(client, monkeypatch):
    import base64

    from svix.webhooks import Webhook

    from sentinel.config import get_settings

    secret = "whsec_" + base64.b64encode(b"0" * 24).decode()
    monkeypatch.setattr(get_settings(), "clerk_webhook_signing_secret", secret)
    body = json.dumps({"type": "organization.created",
                       "data": {"id": "org_hooked", "name": "Hooked Legal"}})
    from datetime import UTC, datetime

    ts = datetime.now(UTC)
    sig = Webhook(secret).sign("msg_1", ts, body)
    headers = {"svix-id": "msg_1", "svix-timestamp": str(int(ts.timestamp())),
               "svix-signature": sig, "content-type": "application/json"}
    assert client.post("/webhooks/clerk", content=body, headers=headers).status_code == 204
    assert client.post("/webhooks/clerk", content=body, headers=headers).status_code == 204
    bad = {**headers, "svix-signature": "v1,AAAA"}
    assert client.post("/webhooks/clerk", content=body, headers=bad).status_code == 400
    me = client.get("/me", headers=hdr("org_hooked")).json()
    assert me["org_name"] == "Hooked Legal"


def test_first_requests_for_a_new_org_can_run_concurrently(client):
    """The dashboard loads several endpoints at once; a brand-new org must not race into a 500."""
    from concurrent.futures import ThreadPoolExecutor

    h = hdr("org_concurrent_first_visit")
    paths = ["/runs", "/repos", "/org/settings"] * 6
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        codes = list(pool.map(lambda p: client.get(p, headers=h).status_code, paths))
    assert set(codes) == {200}
