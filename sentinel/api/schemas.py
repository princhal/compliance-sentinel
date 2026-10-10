"""Request bodies for the API."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class RepoIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, description="Git URL (https) of the repository to audit.")
    default_branch: str = "main"


class RunIn(BaseModel):
    repo_id: uuid.UUID


class ApprovalIn(BaseModel):
    approved: bool = True


class FindingReviewIn(BaseModel):
    review_status: Literal["open", "accepted_risk", "false_positive", "fixed"]


class OrgSettingsIn(BaseModel):
    slack_webhook_url: HttpUrl | None = None
    alert_emails: list[EmailStr] = []
    alert_min_severity: Literal["critical", "high", "medium", "low"] = "critical"
