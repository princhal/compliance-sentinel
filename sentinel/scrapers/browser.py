"""Headless browser helpers for pages that need JavaScript. Playwright is imported lazily."""

from __future__ import annotations

from sentinel.config import get_settings


def render_page(url: str, wait_for: str | None = None, timeout_ms: int = 30000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=get_settings().scrape_user_agent)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()


def list_links(url: str, link_selector: str, timeout_ms: int = 30000) -> list[tuple[str, str]]:
    """Returns (absolute URL, link text) for every link matching the selector."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=get_settings().scrape_user_agent)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_selector(link_selector, timeout=timeout_ms)
            return page.eval_on_selector_all(
                link_selector,
                "els => els.map(e => [e.href, (e.textContent || '').trim()])",
            )
        finally:
            browser.close()
