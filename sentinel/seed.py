"""Demo data: one organization and the bundled demo target repo."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.db.models import Organization, Repo
from sentinel.ingest.pipeline import ensure_sources

DEMO_REPO = Path(__file__).resolve().parent.parent / "demo-target-repo"


def seed_demo(session: Session, clerk_org_id: str = "org_demo",
              name: str = "Demo Legal Team") -> tuple[Organization, Repo]:
    ensure_sources(session)
    org = session.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if org is None:
        org = Organization(clerk_org_id=clerk_org_id, name=name)
        session.add(org)
        session.flush()
    repo = session.scalar(select(Repo).where(Repo.org_id == org.id, Repo.name == "shopwise-demo"))
    if repo is None:
        repo = Repo(org_id=org.id, name="shopwise-demo", url=str(DEMO_REPO))
        session.add(repo)
        session.flush()
    return org, repo
