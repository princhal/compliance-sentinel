"""US Federal Register: uses the official JSON API, no browser needed.

API docs: https://www.federalregister.gov/developers/documentation/api/v1
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.scrapers.base import BaseScraper, DocRef, RawDoc

API = "https://www.federalregister.gov/api/v1/documents.json"


class FederalRegisterScraper(BaseScraper):
    def list_new(self, since: datetime | None) -> list[DocRef]:
        assert self.http is not None
        since = since or datetime.now(UTC) - timedelta(days=int(self.config.get("lookback_days", 30)))
        params: dict[str, object] = {
            "per_page": int(self.config.get("per_page", 20)),
            "order": "newest",
            "conditions[publication_date][gte]": since.date().isoformat(),
            "conditions[type][]": self.config.get("types", ["RULE", "PRORULE"]),
            "fields[]": ["document_number", "title", "html_url", "raw_text_url",
                         "publication_date", "agencies", "type"],
        }
        if term := self.config.get("term"):
            params["conditions[term]"] = term
        resp = self.http.get(API, params=params)
        resp.raise_for_status()
        refs = []
        for doc in resp.json().get("results", []):
            url = doc.get("raw_text_url") or doc["html_url"]
            refs.append(DocRef(
                external_id=doc["document_number"], url=url, title=doc["title"],
                regulation=self.config.get("regulation", "US-FR"),
                published_at=datetime.fromisoformat(doc["publication_date"]).replace(tzinfo=UTC),
                meta={"html_url": doc["html_url"], "type": doc.get("type")},
            ))
        return refs

    def fetch(self, ref: DocRef, etag: str | None = None,
              last_modified: str | None = None) -> RawDoc:
        return self._fetch_http(ref, etag, last_modified)
