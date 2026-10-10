"""Test setup. Database tests use a separate `sentinel_test` database on the docker compose
Postgres and are skipped when it is not reachable."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_DB = "postgresql+psycopg://sentinel:sentinel@localhost:54329/sentinel_test"
DATA_DIR = Path(tempfile.mkdtemp(prefix="sentinel-test-"))
os.environ.update({
    "ENVIRONMENT": "test", "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", TEST_DB),
    "LLM_MODE": "offline", "EMBEDDING_PROVIDER": "hash", "AUTH_MODE": "dev",
    "JOBS_INLINE": "true", "DATA_DIR": str(DATA_DIR), "REQUIRE_APPROVAL": "true",
    "INTERNAL_API_TOKEN": "test-internal-token", "CLERK_WEBHOOK_SIGNING_SECRET": "",
})

ROOT = Path(__file__).resolve().parent.parent


def _db_available() -> bool:
    import psycopg

    admin = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    admin = admin.rsplit("/", 1)[0] + "/sentinel"
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=2) as conn:
            name = os.environ["DATABASE_URL"].rsplit("/", 1)[1]
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            conn.execute(f'CREATE DATABASE "{name}"')
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def database() -> str:
    if not _db_available():
        pytest.skip("Postgres not reachable: run `docker compose up -d`")
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def ingested(database: str) -> dict:
    """Bundled regulations scraped and ingested once for the whole session."""
    from sentinel.db.session import session_scope
    from sentinel.queue.stages import scrape_and_ingest
    from sentinel.seed import seed_demo

    with session_scope() as s:
        seed_demo(s)
    return scrape_and_ingest(["fixtures"])


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(DATA_DIR, ignore_errors=True)
