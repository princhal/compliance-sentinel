"""Structure-aware chunking: one chunk per article paragraph or lettered point.

Legal citations need exact references such as "Art. 32(1)" or "§ 1798.105(c)(1)", so the chunker
splits on the document's own numbering rather than on a fixed token count.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_CHARS = 2500

_MD_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_ARTICLE = re.compile(r"^(?:Article|Art\.)\s+(\d+[a-z]?)\b\.?\s*(.*)$", re.I)
_SECTION = re.compile(r"^(?:§+|Section|Sec\.)\s*([\d]+(?:\.[\d]+)*[a-z]?)\b\.?\s*(.*)$", re.I)
_NUM_PARA = re.compile(r"^(\d+[a-z]?)\.\s+(.*)$", re.S)
_PAREN_LABELS = re.compile(r"^((?:\([a-z0-9]+\))+)\s*(.*)$", re.S | re.I)


@dataclass
class Chunk:
    section_ref: str
    heading: str
    text: str
    context: str

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(f"{self.section_ref}\n{self.text}".encode()).hexdigest()


def _base_ref(line: str) -> tuple[str, str] | None:
    if m := _ARTICLE.match(line):
        return f"Art. {m.group(1)}", f"Article {m.group(1)} {m.group(2)}".strip()
    if m := _SECTION.match(line):
        return f"§ {m.group(1)}", f"Section {m.group(1)} {m.group(2)}".strip()
    return None


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.;])\s+", text):
        if len(cur) + len(sentence) > MAX_CHARS and cur:
            parts.append(cur.strip())
            cur = ""
        cur += sentence + " "
    if cur.strip():
        parts.append(cur.strip())
    return parts


def chunk_text(text: str, regulation: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    base, heading, lead_in, num = "", "", "", ""
    found_structure = False

    def emit(ref: str, body: str) -> None:
        for i, piece in enumerate(_split_long(body)):
            chunks.append(Chunk(section_ref=f"{regulation} {ref}".strip(),
                                heading=heading + (f" (part {i + 1})" if i else ""),
                                text=piece, context=lead_in))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for para in paragraphs:
        first_line = para.splitlines()[0].strip()
        heading_text = _MD_HEADING.match(first_line)
        candidate = heading_text.group(1).strip() if heading_text else first_line
        ref = _base_ref(candidate)
        if ref and (heading_text or len(candidate) < 160):
            found_structure = True
            base, heading = ref
            lead_in, num = "", ""
            rest = "\n".join(para.splitlines()[1:]).strip()
            if not rest:
                continue
            para = rest
        elif heading_text:
            continue  # A heading that is not a legal section, such as a page title.
        if not base:
            continue
        body = re.sub(r"\s+", " ", para)
        if m := _NUM_PARA.match(body):
            num, content = m.group(1), m.group(2)
            if content.rstrip().endswith(":") and len(content) < 300:
                lead_in = content  # e.g. "Personal data shall be:" introduces lettered points.
                continue
            lead_in = ""
            emit(f"{base}({num})", content)
        elif m := _PAREN_LABELS.match(body):
            labels, content = m.group(1), m.group(2)
            prefix = f"({num})" if num and labels[1].isalpha() and labels[1].islower() else ""
            emit(f"{base}{prefix}{labels}", content)
        else:
            emit(base, body)

    if not found_structure:
        # Unstructured text such as a Federal Register notice: windows of whole paragraphs.
        heading, lead_in = "", ""
        buf, n = "", 1
        for para in paragraphs:
            if len(buf) + len(para) > MAX_CHARS and buf:
                emit(f"para {n}", buf)
                buf, n = "", n + 1
            buf += para + "\n\n"
        if buf.strip():
            emit(f"para {n}", buf.strip())
    return chunks
