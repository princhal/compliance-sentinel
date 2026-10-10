"""Index a repo: check it out, chunk every source file and store embeddings for code search."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from sentinel.codebase.chunker import chunk_code
from sentinel.codebase.repo import checkout, iter_source_files
from sentinel.config import Settings, get_settings
from sentinel.db.models import CodeChunk, Repo
from sentinel.embeddings import Embedder

log = logging.getLogger(__name__)


@dataclass
class IndexResult:
    workdir: Path
    commit: str
    chunks: int
    reused: bool


def index_repo(session: Session, repo: Repo, embedder: Embedder,
               settings: Settings | None = None) -> IndexResult:
    settings = settings or get_settings()
    workdir, commit = checkout(repo.url, settings.repos_dir / str(repo.id), None)
    existing = session.scalar(select(func.count()).select_from(CodeChunk).where(
        CodeChunk.repo_id == repo.id, CodeChunk.commit == commit)) or 0
    if existing:
        return IndexResult(workdir, commit, existing, reused=True)

    rows: list[CodeChunk] = []
    for path, lang in iter_source_files(workdir):
        rel = str(path.relative_to(workdir))
        text = path.read_text(errors="replace")
        for span in chunk_code(text, lang):
            body = f"# {rel} :: {span.symbol}\n{span.text}"
            rows.append(CodeChunk(org_id=repo.org_id, repo_id=repo.id, commit=commit, path=rel,
                                  symbol=span.symbol, start_line=span.start_line,
                                  end_line=span.end_line, language=lang, text=span.text,
                                  content_hash=hashlib.sha256(body.encode()).hexdigest()))
    vectors = embedder.embed_documents([f"{r.path} {r.symbol}\n{r.text}" for r in rows], "code")
    for row, vec in zip(rows, vectors, strict=True):
        row.embedding = vec
    # Keep only the latest commit's chunks for this repo.
    session.execute(delete(CodeChunk).where(CodeChunk.repo_id == repo.id,
                                            CodeChunk.commit != commit))
    session.add_all(rows)
    repo.last_commit, repo.last_indexed_at = commit, datetime.now(UTC)
    session.flush()
    log.info("Indexed %s at %s: %s chunks", repo.name, commit[:12], len(rows))
    return IndexResult(workdir, commit, len(rows), reused=False)


def read_lines(workdir: Path, rel: str, start: int, end: int, pad: int = 0) -> str:
    """Return numbered source lines, so evidence in prompts and reports shows real line numbers."""
    path = (workdir / rel).resolve()
    if not path.is_relative_to(workdir.resolve()) or not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()
    a, b = max(1, start - pad), min(len(lines), end + pad)
    return "\n".join(f"{i:>5} | {lines[i - 1]}" for i in range(a, b + 1))
