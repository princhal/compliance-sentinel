"""EUR-Lex: watches a configured list of acts by CELEX number.

EUR-Lex sometimes serves a JavaScript challenge to plain HTTP clients. In that case the scraper
falls back to a headless Chromium page through Playwright.
"""

from __future__ import annotations

from datetime import datetime

from sentinel.scrapers.base import BaseScraper, DocRef, RawDoc
from sentinel.scrapers.browser import render_page

URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex}"


class EurLexScraper(BaseScraper):
    def list_new(self, since: datetime | None) -> list[DocRef]:
        # Acts are watched for changes by content hash, so every configured act is listed.
        return [DocRef(external_id=f"CELEX-{a['celex']}", url=URL.format(celex=a["celex"]),
                       title=a["title"], regulation=a.get("regulation", "EU"))
                for a in self.config.get("acts", [])]

    def fetch(self, ref: DocRef, etag: str | None = None,
              last_modified: str | None = None) -> RawDoc:
        raw = self._fetch_http(ref, etag, last_modified)
        if raw.not_modified or b"Article" in raw.content:
            return raw
        html = render_page(ref.url, wait_for=self.config.get("wait_for", "#document1, .eli-container"))
        return RawDoc(ref=ref, content=html.encode(), content_type="text/html")
