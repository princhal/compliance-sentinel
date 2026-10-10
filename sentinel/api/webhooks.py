"""Clerk webhooks (delivered by Svix): keep users, organizations and memberships in sync."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from svix.webhooks import Webhook, WebhookVerificationError

from sentinel.auth.deps import get_db
from sentinel.config import Settings, get_settings
from sentinel.db.models import Membership, Organization, User, WebhookEvent

log = logging.getLogger(__name__)
router = APIRouter()


def _user(db: Session, clerk_id: str) -> User:
    u = db.scalar(select(User).where(User.clerk_user_id == clerk_id))
    if u is None:
        u = User(clerk_user_id=clerk_id)
        db.add(u)
        db.flush()
    return u


def _org(db: Session, clerk_id: str) -> Organization:
    o = db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_id))
    if o is None:
        o = Organization(clerk_org_id=clerk_id, name=clerk_id)
        db.add(o)
        db.flush()
    return o


def apply_event(db: Session, event_type: str, data: dict) -> None:
    if event_type in ("user.created", "user.updated"):
        u = _user(db, data["id"])
        emails = data.get("email_addresses") or []
        primary = next((e["email_address"] for e in emails
                        if e.get("id") == data.get("primary_email_address_id")), None)
        u.email = primary or (emails[0]["email_address"] if emails else u.email)
        u.name = " ".join(p for p in (data.get("first_name"), data.get("last_name")) if p) or u.name
    elif event_type == "user.deleted" and data.get("id"):
        db.execute(delete(User).where(User.clerk_user_id == data["id"]))
    elif event_type in ("organization.created", "organization.updated"):
        _org(db, data["id"]).name = data.get("name") or data["id"]
    elif event_type == "organization.deleted" and data.get("id"):
        db.execute(delete(Organization).where(Organization.clerk_org_id == data["id"]))
    elif event_type in ("organizationMembership.created", "organizationMembership.updated"):
        org = _org(db, data["organization"]["id"])
        user = _user(db, data["public_user_data"]["user_id"])
        m = db.scalar(select(Membership).where(Membership.org_id == org.id,
                                               Membership.user_id == user.id))
        if m is None:
            db.add(Membership(org_id=org.id, user_id=user.id, role=data.get("role", "org:member")))
        else:
            m.role = data.get("role", m.role)
    elif event_type == "organizationMembership.deleted":
        org = db.scalar(select(Organization).where(
            Organization.clerk_org_id == data["organization"]["id"]))
        user = db.scalar(select(User).where(
            User.clerk_user_id == data["public_user_data"]["user_id"]))
        if org and user:
            db.execute(delete(Membership).where(Membership.org_id == org.id,
                                                Membership.user_id == user.id))


@router.post("/webhooks/clerk", status_code=204)
async def clerk_webhook(request: Request, db: Session = Depends(get_db),
                        settings: Settings = Depends(get_settings)) -> None:
    if not settings.clerk_webhook_signing_secret:
        raise HTTPException(503, "Webhook signing secret is not configured")
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.startswith("svix-")}
    try:
        # svix 2.x verify() only raises on a bad signature and returns nothing.
        Webhook(settings.clerk_webhook_signing_secret).verify(body, headers)
    except WebhookVerificationError as exc:
        raise HTTPException(400, "Invalid signature") from exc
    event = json.loads(body)
    svix_id = headers.get("svix-id", "")
    if db.get(WebhookEvent, svix_id) is not None:
        return  # Svix retried a delivery we already processed.
    apply_event(db, event["type"], event.get("data", {}))
    db.add(WebhookEvent(svix_id=svix_id, type=event["type"]))
