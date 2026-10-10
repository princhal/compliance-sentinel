"""Reads bundled regulation excerpts. Lets the whole pipeline run offline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from sentinel.scrapers.base import BaseScraper, DocRef, RawDoc

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "regulations"


def split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body.lstrip()
    return {}, text


class FixtureScraper(BaseScraper):
    def _dir(self) -> Path:
        return Path(self.config.get("path") or FIXTURE_DIR)

    def list_new(self, since: datetime | None) -> list[DocRef]:
        refs = []
        for path in sorted(self._dir().glob("*.md")):
            meta, _ = split_front_matter(path.read_text())
            published = meta.get("published_at")
            if isinstance(published, str):
                published = datetime.fromisoformat(published)
            elif published is not None and not isinstance(published, datetime):
                published = datetime(published.year, published.month, published.day)
            if published is not None and published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            refs.append(DocRef(external_id=meta["external_id"], url=meta["url"],
                               title=meta["title"], regulation=meta["regulation"],
                               published_at=published, meta={"path": str(path), **meta}))
        return refs

    def fetch(self, ref: DocRef, etag: str | None = None,
              last_modified: str | None = None) -> RawDoc:
        return RawDoc(ref=ref, content=Path(ref.meta["path"]).read_bytes(),
                      content_type="text/markdown")
