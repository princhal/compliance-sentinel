"""FastAPI dependencies: the current principal, their org row and role checks."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import ColumnElement, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    # The dashboard fires several requests at once, so a new org's first page load races here;
    # ON CONFLICT DO NOTHING lets every request settle on the same rows instead of failing.
    org = _get_or_create(db, Organization, Organization.clerk_org_id == principal.org_id,
                         clerk_org_id=principal.org_id, name=principal.org_id)
    user = _get_or_create(db, User, User.clerk_user_id == principal.user_id,
                          clerk_user_id=principal.user_id, email=principal.email)
    member = _get_or_create(db, Membership, (Membership.org_id == org.id) & (Membership.user_id == user.id),
                            org_id=org.id, user_id=user.id, role=principal.role or "org:member")
    if principal.role and member.role != principal.role:
        member.role = principal.role
    db.flush()
    return OrgContext(principal=principal, org=org, user=user)


def _get_or_create[T](db: Session, model: type[T], where: ColumnElement[bool], **values: object) -> T:
    row = db.scalar(select(model).where(where))
    if row is None:
        db.execute(pg_insert(model).values(**values).on_conflict_do_nothing())
        row = db.scalars(select(model).where(where)).one()
    return row


def require_role(*roles: str) -> Callable[[OrgContext], OrgContext]:
    """Admins pass every check. Other roles must be listed."""

    def check(ctx: OrgContext = Depends(current_org)) -> OrgContext:
        if ctx.principal.role == ROLE_ADMIN or ctx.principal.role in roles:
            return ctx
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot do this")

    return check
