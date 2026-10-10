"""Command line interface: `sentinel --help`."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import typer
from sqlalchemy import select


def _ensure_macos_libs() -> None:
    """WeasyPrint loads Pango through dlopen. On macOS with Homebrew, dyld only searches
    /opt/homebrew/lib when DYLD_FALLBACK_LIBRARY_PATH is set at process start, so re-exec once."""
    import os
    import sys

    brew = "/opt/homebrew/lib"
    if sys.platform == "darwin" and os.path.isdir(brew) and \
            brew not in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", ""):
        env = {**os.environ, "DYLD_FALLBACK_LIBRARY_PATH": brew}
        os.execve(sys.executable, [sys.executable, "-m", "sentinel.cli", *sys.argv[1:]], env)  # noqa: S606


_ensure_macos_libs()

app = typer.Typer(help="Compliance Sentinel", no_args_is_help=True)


def _logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "fontTools", "weasyprint", "trafilatura"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    _logging(verbose)


@app.command("db-upgrade")
def db_upgrade() -> None:
    """Apply database migrations."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")


@app.command()
def seed() -> None:
    """Create the regulatory sources, a demo org and the demo target repo."""
    from sentinel.db.session import session_scope
    from sentinel.seed import seed_demo

    with session_scope() as s:
        org, repo = seed_demo(s)
        typer.echo(f"org={org.id} ({org.clerk_org_id}) repo={repo.id} ({repo.url})")


@app.command()
def scrape(source: list[str] = typer.Option(None, "--source", "-s"),
           fixture_dir: Path = typer.Option(None, help="Override the fixture directory.")) -> None:
    """Scrape sources and ingest changed documents."""
    from sentinel.queue.stages import scrape_and_ingest

    out = scrape_and_ingest(source or None,
                            {"path": str(fixture_dir)} if fixture_dir else None)
    typer.echo(json.dumps(out, indent=2, default=str))


@app.command()
def audit(repo: str = typer.Option("shopwise-demo"), org: str = typer.Option("org_demo"),
          approve_as: str = typer.Option(None, help="Approve immediately as this name."),
          changed_only: bool = typer.Option(False, help="Only obligations from the last ingest.")
          ) -> None:
    """Run an audit for one repo."""
    from sentinel.agent.runner import create_run, resume_audit, run_audit
    from sentinel.db.models import Organization, Repo
    from sentinel.db.session import session_scope

    with session_scope() as s:
        o = s.scalar(select(Organization).where(Organization.clerk_org_id == org))
        r = s.scalar(select(Repo).where(Repo.org_id == o.id, Repo.name == repo))
        org_id, repo_id = o.id, r.id
    run_id = create_run(org_id, repo_id, trigger="manual", triggered_by="cli")
    typer.echo(f"run {run_id}")
    result = run_audit(run_id)
    if "__interrupt__" in result:
        typer.echo("Run is waiting for approval.")
        if approve_as:
            result = resume_audit(run_id, True, "cli", approve_as)
    _print_run(run_id)


@app.command()
def approve(run_id: str, name: str = typer.Option(..., help="Approver name for the PDF."),
            reject: bool = typer.Option(False)) -> None:
    """Approve or reject a run that is waiting for approval."""
    from sentinel.agent.runner import resume_audit

    resume_audit(uuid.UUID(run_id), not reject, "cli", name)
    _print_run(uuid.UUID(run_id))


def _print_run(run_id: uuid.UUID) -> None:
    from sentinel.db.models import AuditRun, Report
    from sentinel.db.session import session_scope

    with session_scope() as s:
        run = s.get(AuditRun, run_id)
        rep = s.scalar(select(Report).where(Report.run_id == run_id))
        typer.echo(json.dumps({"run": str(run.id), "status": run.status, "commit": run.commit,
                               "engine": run.llm_engine, "stats": run.stats,
                               "cost_usd": run.cost_usd,
                               "report": rep.pdf_path if rep else None,
                               "report_sha256": rep.sha256 if rep else None}, indent=2))


@app.command()
def worker() -> None:
    """Run all BullMQ queue workers."""
    import asyncio

    from sentinel.queue.worker import run_workers

    asyncio.run(run_workers())


@app.command()
def scheduler() -> None:
    """Register the daily scrape schedule in Redis."""
    import asyncio

    from sentinel.queue.schedule import register_schedules

    asyncio.run(register_schedules())


@app.command()
def api(host: str = "0.0.0.0", port: int = 8000) -> None:  # noqa: S104
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("sentinel.api.app:app", host=host, port=port, proxy_headers=True)


@app.command("eval")
def run_eval(run_id: str = typer.Option(None, help="Score an existing run (default: latest)."),
             out: Path = typer.Option(Path("evals/results.json"))) -> None:
    """Score findings against evals/golden.yaml and retrieval against evals/rag_questions.yaml."""
    from evals.score import main as score_main

    score_main(run_id, out)


if __name__ == "__main__":
    app()
