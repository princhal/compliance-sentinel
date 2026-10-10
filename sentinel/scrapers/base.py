"""Scraper interface and a polite HTTP client shared by all scrapers."""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from sentinel.config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class DocRef:
    external_id: str
    url: str
    title: str
    regulation: str
    published_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawDoc:
    ref: DocRef
    content: bytes
    content_type: str
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class RobotsDisallowed(RuntimeError):
    pass


class PoliteClient:
    """httpx client that respects robots.txt, throttles per domain and retries with backoff."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = httpx.Client(
            headers={"User-Agent": self.settings.scrape_user_agent},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            transport=httpx.HTTPTransport(retries=2),
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = self.client.get(f"{base}/robots.txt")
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
                self._robots[base] = rp
            except httpx.HTTPError:
                self._robots[base] = None  # Unreachable robots.txt: treat as allowed.
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.settings.scrape_user_agent, url)

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        wait = self.settings.scrape_min_delay_s - (time.monotonic() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, *, etag: str | None = None, last_modified: str | None = None,
            params: dict[str, Any] | None = None) -> httpx.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        delay = 2.0
        for attempt in range(4):
            self._throttle(url)
            resp = self.client.get(url, headers=headers, params=params)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                retry_after = resp.headers.get("retry-after", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else delay)
                delay *= 2
                continue
            return resp
        return resp


class BaseScraper(ABC):
    def __init__(self, source_key: str, config: dict[str, Any],
                 client: PoliteClient | None = None) -> None:
        self.source_key = source_key
        self.config = config
        self.http = client

    @abstractmethod
    def list_new(self, since: datetime | None) -> list[DocRef]:
        """Documents published or changed since the given time."""

    @abstractmethod
    def fetch(self, ref: DocRef, etag: str | None = None,
              last_modified: str | None = None) -> RawDoc:
        """Download one document. Returns not_modified=True when the server says it is unchanged."""

    def _fetch_http(self, ref: DocRef, etag: str | None, last_modified: str | None) -> RawDoc:
        assert self.http is not None
        resp = self.http.get(ref.url, etag=etag, last_modified=last_modified)
        if resp.status_code == 304:
            return RawDoc(ref=ref, content=b"", content_type="", not_modified=True)
        resp.raise_for_status()
        return RawDoc(ref=ref, content=resp.content,
                      content_type=resp.headers.get("content-type", "text/html").split(";")[0],
                      etag=resp.headers.get("etag"),
                      last_modified=resp.headers.get("last-modified"))
