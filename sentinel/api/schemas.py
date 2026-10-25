"""Request bodies for the API."""

from __future__ import annotations

import ipaddress
import re
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator

from sentinel.config import get_settings

# Git ref names: no leading "-", "/" or ".", no "..", spaces or the characters git forbids.
BRANCH_RE = re.compile(r"^(?![-./])(?!.*\.\.)(?!.*[/.]$)[A-Za-z0-9._/-]+$")


def _is_internal_host(host: str) -> bool:
    if host == "localhost" or host.endswith((".localhost", ".internal", ".local")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # A hostname; DNS is not resolved here.
    return not ip.is_global


class RepoIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048,
                     description="Git URL (https) of the repository to audit.")
    default_branch: str = Field("main", min_length=1, max_length=128)

    @field_validator("default_branch")
    @classmethod
    def _check_branch(cls, v: str) -> str:
        if not BRANCH_RE.match(v):
            raise ValueError("Invalid branch name")
        return v

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip()
        # A leading "-" would reach `git clone` as an option, and control characters never belong.
        if v.startswith("-") or any(ord(c) < 32 for c in v):
            raise ValueError("Invalid repository URL")
        parts = urlsplit(v)
        if parts.scheme == "https":
            if not parts.hostname or _is_internal_host(parts.hostname):
                raise ValueError("Use a public https:// git URL")
            if parts.username or parts.password:
                raise ValueError("Do not put credentials in the repository URL")
            return v
        # Outside production a local checkout may be audited in place (demo, tests, local dev).
        if get_settings().environment != "production" and not parts.scheme and Path(v).exists():
            return v
        raise ValueError("Use an https:// git URL")


class RunIn(BaseModel):
    repo_id: uuid.UUID


class ApprovalIn(BaseModel):
    approved: bool = True


class FindingReviewIn(BaseModel):
    review_status: Literal["open", "accepted_risk", "false_positive", "fixed"]


class OrgSettingsIn(BaseModel):
    slack_webhook_url: HttpUrl | None = None  # Omitted or null keeps the current webhook.
    clear_slack: bool = False
    alert_emails: list[EmailStr] = []
    alert_min_severity: Literal["critical", "high", "medium", "low"] = "critical"
