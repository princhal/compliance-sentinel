"""Source definitions. Selectors live here, so a site redesign is a config change."""

from __future__ import annotations

from typing import Any

from sentinel.scrapers.base import BaseScraper, PoliteClient
from sentinel.scrapers.eurlex import EurLexScraper
from sentinel.scrapers.federal_register import FederalRegisterScraper
from sentinel.scrapers.fixture import FixtureScraper
from sentinel.scrapers.guidance import GuidancePageScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    "fixture": FixtureScraper,
    "federal_register": FederalRegisterScraper,
    "eurlex": EurLexScraper,
    "guidance": GuidancePageScraper,
}

DEFAULT_SOURCES: list[dict[str, Any]] = [
    {"key": "fixtures", "name": "Bundled regulation excerpts (offline demo)", "kind": "fixture",
     "url": "file://sentinel/fixtures/regulations", "jurisdiction": "multi",
     "config": {"scraper": "fixture"}, "enabled": True},
    {"key": "federal-register-privacy", "name": "US Federal Register: privacy rules", "kind": "api",
     "url": "https://www.federalregister.gov/api/v1", "jurisdiction": "US",
     "config": {"scraper": "federal_register", "term": "privacy personal information",
                "regulation": "US-FR", "lookback_days": 14, "per_page": 10},
     "enabled": False},
    {"key": "eurlex-gdpr", "name": "EUR-Lex: GDPR consolidated text", "kind": "html",
     "url": "https://eur-lex.europa.eu", "jurisdiction": "EU",
     "config": {"scraper": "eurlex",
                "acts": [{"celex": "32016R0679", "title": "General Data Protection Regulation",
                          "regulation": "GDPR"}]},
     "enabled": False},
    {"key": "ico-guidance", "name": "UK ICO: UK GDPR guidance", "kind": "html",
     "url": "https://ico.org.uk", "jurisdiction": "UK",
     "config": {"scraper": "guidance", "regulation": "UK-GDPR-guidance",
                "index_url": "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/",
                "link_selector": "main a[href*='/for-organisations/uk-gdpr-guidance-and-resources/']",
                "max_documents": 10},
     "enabled": False},
]


def scraper_for(source_key: str, config: dict[str, Any],
                client: PoliteClient | None = None) -> BaseScraper:
    kind = config.get("scraper", "fixture")
    if kind != "fixture" and client is None:
        client = PoliteClient()
    return SCRAPERS[kind](source_key, config, client)
