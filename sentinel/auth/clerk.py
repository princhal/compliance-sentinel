"""Clerk session token verification and the request principal.

The token is the source of truth for who the user is, which organization is active and what role
they hold. Webhooks only keep display data (names, emails) in sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import HTTPException, Request, status

from sentinel.config import Settings

log = logging.getLogger(__name__)

ROLE_ADMIN, ROLE_AUDITOR, ROLE_MEMBER = "org:admin", "org:auditor", "org:member"


@dataclass
class Principal:
    user_id: str
    org_id: str | None
    role: str | None
    permissions: list[str] = field(default_factory=list)
    email: str | None = None


def _norm_role(role: str | None) -> str | None:
    if not role:
        return None
    return role if role.startswith("org:") else f"org:{role}"


def principal_from_claims(claims: dict) -> Principal:
    """Handles both Clerk session token formats: v2 nests the org under "o", v1 is flat."""
    org = claims.get("o") or {}
    org_id = org.get("id") or claims.get("org_id")
    role = _norm_role(org.get("rol") or claims.get("org_role"))
    perms = claims.get("org_permissions") or []
    if isinstance(org.get("per"), str):
        perms = [f"org:{p}" for p in org["per"].split(",") if p]
    return Principal(user_id=claims["sub"], org_id=org_id, role=role, permissions=list(perms),
                     email=claims.get("email"))


def verify_clerk(request: Request, settings: Settings) -> Principal:
    state = authenticate_request(request, AuthenticateRequestOptions(
        secret_key=settings.clerk_secret_key or None,
        jwt_key=settings.clerk_jwt_key or None,  # Enables networkless verification.
        authorized_parties=settings.clerk_authorized_parties or None,
    ))
    if not state.is_signed_in or not state.payload:
        log.info("Rejected request: %s", state.message)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return principal_from_claims(state.payload)


def verify_dev(request: Request) -> Principal:
    """Local development only. Settings refuse AUTH_MODE=dev when ENVIRONMENT=production."""
    user = request.headers.get("x-dev-user", "user_dev")
    return Principal(user_id=user, org_id=request.headers.get("x-dev-org", "org_demo"),
                     role=_norm_role(request.headers.get("x-dev-role", "admin")))
