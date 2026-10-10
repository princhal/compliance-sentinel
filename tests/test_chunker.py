from pathlib import Path

from sentinel.ingest.chunker import chunk_text
from sentinel.ingest.parse import to_text

FIX = Path(__file__).resolve().parent.parent / "sentinel" / "fixtures" / "regulations"


def refs(name: str, reg: str) -> list[str]:
    text = to_text((FIX / f"{name}.md").read_bytes(), "text/markdown")
    return [c.section_ref for c in chunk_text(text, reg)]


def test_gdpr_paragraph_and_point_references():
    r = refs("gdpr", "GDPR")
    assert "GDPR Art. 5(1)(c)" in r and "GDPR Art. 5(1)(f)" in r
    assert "GDPR Art. 32(1)" in r and "GDPR Art. 44" in r


def test_lead_in_becomes_context_not_a_chunk():
    text = to_text((FIX / "gdpr.md").read_bytes(), "text/markdown")
    chunks = {c.section_ref: c for c in chunk_text(text, "GDPR")}
    assert "GDPR Art. 5(1)" not in chunks
    assert chunks["GDPR Art. 5(1)(e)"].context == "Personal data shall be:"


def test_us_code_style_references():
    assert "CCPA § 1798.105(c)(1)" in refs("ccpa", "CCPA")
    assert "HIPAA § 164.312(a)(2)(iv)" in refs("hipaa", "HIPAA")


def test_unstructured_text_falls_back_to_paragraph_windows():
    chunks = chunk_text("First paragraph.\n\nSecond paragraph.", "US-FR")
    assert [c.section_ref for c in chunks] == ["US-FR para 1"]


def test_long_paragraphs_are_split():
    long = "# Article 9 Test\n\n1. " + " ".join(["The controller shall do things."] * 200)
    chunks = chunk_text(long, "X")
    assert len(chunks) > 1 and all(c.section_ref == "X Art. 9(1)" for c in chunks)


def test_live_eurlex_html_keeps_exact_citations():
    """Real EUR-Lex page (Regulation (EU) 2016/679, (c) European Union, https://eur-lex.europa.eu)
    saved by the scraper's browser fallback. Covers HTML extraction quirks: escaped numbering,
    points rendered as table rows, and bare article headings followed by a title line."""
    import gzip

    html = gzip.decompress((Path(__file__).parent / "fixtures" / "eurlex_gdpr_32016R0679.html.gz")
                           .read_bytes())
    chunks = {}
    for c in chunk_text(to_text(html, "text/html"), "GDPR"):
        chunks.setdefault(c.section_ref, c)
    assert chunks["GDPR Art. 32(1)(a)"].text.startswith("the pseudonymisation and encryption")
    assert chunks["GDPR Art. 32(1)"].heading == "Article 32 Security of processing"
    assert chunks["GDPR Art. 17(1)"].text.startswith("The data subject shall have the right")
    assert chunks["GDPR Art. 17(1)(b)"].context.startswith("The data subject shall have the right")
    assert chunks["GDPR Art. 5(1)(e)"].context == "Personal data shall be:"
