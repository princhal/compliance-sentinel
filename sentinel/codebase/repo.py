"""Check out a target repo at a pinned commit and walk its source files."""

from __future__ import annotations

import hashlib
import shutil
import subprocess  # noqa: S404 - git is invoked with fixed arguments, never through a shell.
from collections.abc import Iterator
from pathlib import Path

SOURCE_EXT = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
              ".tsx": "tsx", ".go": "go", ".java": "java", ".rb": "ruby", ".yaml": "yaml",
              ".yml": "yaml", ".toml": "toml", ".env": "dotenv", ".sql": "sql", ".tf": "hcl"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             "vendor", "site-packages"}
MAX_FILE_BYTES = 400_000


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,  # noqa: S603,S607
                          text=True, timeout=300).stdout.strip()


def checkout(url: str, dest: Path, ref: str | None = None) -> tuple[Path, str]:
    """Returns (working directory, commit SHA). Local paths that are not git repos are used in
    place, with a content hash standing in for the commit."""
    local = Path(url).expanduser()
    if local.exists():
        if (local / ".git").exists():
            return local, _git("rev-parse", "HEAD", cwd=local)
        return local, "workdir-" + tree_hash(local)[:12]
    if dest.exists() and (dest / ".git").exists():
        _git("fetch", "--depth", "1", "origin", ref or "HEAD", cwd=dest)
        _git("checkout", "--force", "FETCH_HEAD", cwd=dest)
    else:
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--depth", "1"] + (["--branch", ref] if ref else []) + [url, str(dest)]
        _git(*args)
    return dest, _git("rev-parse", "HEAD", cwd=dest)


def iter_source_files(root: Path) -> Iterator[tuple[Path, str]]:
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        lang = SOURCE_EXT.get(path.suffix) or ("dotenv" if path.name.startswith(".env") else None)
        if lang:
            yield path, lang


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path, _ in iter_source_files(root):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()
