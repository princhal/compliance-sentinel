"""Guidance pages such as the ICO, EDPB and California CPPA. Driven entirely by config.

Each source lists its index page and a CSS selector for document links. Layout changes only need a
config update, not code.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sentinel.scrapers.base import BaseScraper, DocRef, RawDoc
from sentinel.scrapers.browser import list_links, render_page


class GuidancePageScraper(BaseScraper):
    def list_new(self, since: datetime | None) -> list[DocRef]:
        links = list_links(self.config["index_url"], self.config["link_selector"])
        limit = int(self.config.get("max_documents", 10))
        refs = []
        for href, text in links[:limit]:
            if self.http is not None and not self.http.allowed(href):
                continue
            refs.append(DocRef(external_id=hashlib.sha1(href.encode()).hexdigest()[:16],  # noqa: S324
                               url=href, title=text or href,
                               regulation=self.config.get("regulation", "guidance")))
        return refs

    def fetch(self, ref: DocRef, etag: str | None = None,
              last_modified: str | None = None) -> RawDoc:
        if self.config.get("needs_js"):
            html = render_page(ref.url, wait_for=self.config.get("content_selector"))
            return RawDoc(ref=ref, content=html.encode(), content_type="text/html")
        return self._fetch_http(ref, etag, last_modified)
