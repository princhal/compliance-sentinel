"""FastAPI dependencies: the current principal, their org row and role checks."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.auth.clerk import ROLE_ADMIN, Principal, verify_clerk, verify_dev
from sentinel.config import Settings, get_settings
from sentinel.db.models import Membership, Organization, User
from sentinel.db.session import session_scope


def get_db() -> Iterator[Session]:
    with session_scope() as s:
        yield s


def current_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal:
    if settings.auth_mode == "dev":
        return verify_dev(request)
    return verify_clerk(request, settings)


@dataclass
class OrgContext:
    principal: Principal
    org: Organization
    user: User


def current_org(principal: Principal = Depends(current_principal),
                db: Session = Depends(get_db)) -> OrgContext:
    if not principal.org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Select an organization first")
    # Upsert lazily: the token is authoritative even if the Clerk webhook has not arrived yet.
    org = db.scalar(select(Organization).where(Organization.clerk_org_id == principal.org_id))
    if org is None:
        org = Organization(clerk_org_id=principal.org_id, name=principal.org_id)
        db.add(org)
    user = db.scalar(select(User).where(User.clerk_user_id == principal.user_id))
    if user is None:
        user = User(clerk_user_id=principal.user_id, email=principal.email)
        db.add(user)
    db.flush()
    member = db.scalar(select(Membership).where(Membership.org_id == org.id,
                                                Membership.user_id == user.id))
    if member is None:
        db.add(Membership(org_id=org.id, user_id=user.id, role=principal.role or "org:member"))
    elif principal.role and member.role != principal.role:
        member.role = principal.role
    db.flush()
    return OrgContext(principal=principal, org=org, user=user)


def require_role(*roles: str) -> Callable[[OrgContext], OrgContext]:
    """Admins pass every check. Other roles must be listed."""

    def check(ctx: OrgContext = Depends(current_org)) -> OrgContext:
        if ctx.principal.role == ROLE_ADMIN or ctx.principal.role in roles:
            return ctx
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot do this")

    return check
