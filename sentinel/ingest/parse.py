"""Turn raw HTML, PDF, Markdown or text into plain text that keeps the legal headings."""

from __future__ import annotations

from sentinel.scrapers.fixture import split_front_matter


def to_text(content: bytes, content_type: str) -> str:
    ct = content_type.lower()
    if "markdown" in ct:
        _, body = split_front_matter(content.decode("utf-8", errors="replace"))
        return body
    if "pdf" in ct:
        import pymupdf

        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            return "\n".join(page.get_text() for page in pdf)
    if "html" in ct or "xml" in ct:
        import trafilatura

        text = trafilatura.extract(content.decode("utf-8", errors="replace"),
                                   output_format="markdown", include_tables=True,
                                   include_comments=False, favor_recall=True)
        return text or ""
    return content.decode("utf-8", errors="replace")
