import httpx
import respx

from sentinel.config import Settings
from sentinel.notify.notifier import Alert, Notifier, slack_blocks

ALERT = Alert(org_name="Acme", repo_name="shop", run_id="r1", commit="abc123def456789",
              dashboard_url="https://app.test",
              findings=[{"severity": "critical", "category": "password_storage", "path": "a.py",
                         "start_line": 3, "citation": "GDPR Art. 32(1)", "label": "Weak hash"}])


def test_slack_blocks_link_to_run():
    blocks = slack_blocks(ALERT)["blocks"]
    assert blocks[-1]["elements"][0]["url"] == "https://app.test/runs/r1"


@respx.mock
def test_sends_slack_and_email():
    slack = respx.post("https://hooks.slack.test/x").mock(return_value=httpx.Response(200))
    resend = respx.post("https://api.resend.com/emails").mock(return_value=httpx.Response(200))
    n = Notifier(Settings(resend_api_key="re_test"))
    assert n.send(ALERT, "https://hooks.slack.test/x", ["a@b.test"]) == ["slack", "email"]
    assert slack.called and resend.called


def test_falls_back_to_log_without_channels():
    assert Notifier(Settings()).send(ALERT, None, []) == ["log"]
