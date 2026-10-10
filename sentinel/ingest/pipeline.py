"""Scrape and ingest stages.

scrape_source: fetch new or changed documents and store the raw bytes.
ingest_document: parse, diff against the last version, chunk, embed and extract obligations.
Only chunks whose text changed are re-embedded and re-extracted, and only new obligations trigger
a re-audit.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sentinel.db.models import Document, DocumentVersion, Obligation, RegChunk, Source
from sentinel.embeddings import Embedder
from sentinel.ingest.chunker import Chunk, chunk_text
from sentinel.ingest.parse import to_text
from sentinel.llm import Engine, ObligationDraft
from sentinel.scrapers import DEFAULT_SOURCES, scraper_for
from sentinel.storage import Storage

log = logging.getLogger(__name__)
EXT = {"text/markdown": "md", "application/pdf": "pdf", "text/plain": "txt"}


def ensure_sources(session: Session) -> None:
    existing = set(session.scalars(select(Source.key)))
    for spec in DEFAULT_SOURCES:
        if spec["key"] not in existing:
            session.add(Source(**spec))
    session.flush()


@dataclass
class ScrapeResult:
    source_key: str
    changed_document_ids: list[uuid.UUID] = field(default_factory=list)
    unchanged: int = 0
    error: str | None = None


def scrape_source(session: Session, source: Source, storage: Storage,
                  config_override: dict | None = None) -> ScrapeResult:
    result = ScrapeResult(source.key)
    scraper = scraper_for(source.key, {**source.config, **(config_override or {})})
    try:
        refs = scraper.list_new(source.last_checked_at)
        for ref in refs:
            doc = session.scalar(select(Document).where(Document.source_id == source.id,
                                                        Document.external_id == ref.external_id))
            raw = scraper.fetch(ref, etag=doc.etag if doc else None,
                                last_modified=doc.last_modified if doc else None)
            if raw.not_modified:
                result.unchanged += 1
                continue
            digest = hashlib.sha256(raw.content).hexdigest()
            if doc and doc.content_hash == digest:
                doc.fetched_at = datetime.now(UTC)
                result.unchanged += 1
                continue
            key = (f"raw/{source.key}/{re.sub(r'[^A-Za-z0-9._-]', '_', ref.external_id)}/"
                   f"{digest[:16]}.{EXT.get(raw.content_type, 'html')}")
            raw_path = storage.put(key, raw.content, raw.content_type)
            if doc is None:
                doc = Document(source_id=source.id, external_id=ref.external_id,
                               regulation=ref.regulation, title=ref.title, url=ref.url,
                               published_at=ref.published_at, content_hash=digest,
                               raw_path=raw_path, content_type=raw.content_type)
                session.add(doc)
            doc.title, doc.url, doc.published_at = ref.title, ref.url, ref.published_at
            doc.content_hash, doc.raw_path, doc.content_type = digest, raw_path, raw.content_type
            doc.etag, doc.last_modified = raw.etag, raw.last_modified
            doc.fetched_at, doc.status = datetime.now(UTC), "fetched"
            session.flush()
            result.changed_document_ids.append(doc.id)
        source.last_error = None
    except Exception as exc:  # A broken source must not stop the other sources.
        log.exception("Scrape failed for %s", source.key)
        source.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        result.error = source.last_error
    source.last_checked_at = datetime.now(UTC)
    session.flush()
    return result


@dataclass
class IngestResult:
    document_id: uuid.UUID
    version: int
    new_chunks: int = 0
    retired_chunks: int = 0
    new_obligation_ids: list[uuid.UUID] = field(default_factory=list)
    retired_obligation_ids: list[uuid.UUID] = field(default_factory=list)
    diff: str = ""


_DUTY = re.compile(r"\b(shall|must|required|prohibit|may not|has the right|have the right)\b", re.I)
_PRIVACY = re.compile(r"personal (data|information)|privacy|data subject|consumer|protected health|"
                      r"\bPHI\b|encrypt|breach|consent|retain|retention|security|confidential", re.I)
PRIVACY_REGULATIONS = {"GDPR", "UK-GDPR", "UK-GDPR-guidance", "CCPA", "CPRA", "HIPAA"}


def worth_extracting(chunk: Chunk, regulation: str) -> bool:
    """Cheap gate before the LLM: no duty language means no obligation. Text from general sources
    (e.g. the whole Federal Register) must also be about privacy or security."""
    body = f"{chunk.context} {chunk.text}"
    if not _DUTY.search(body):
        return False
    return regulation in PRIVACY_REGULATIONS or bool(_PRIVACY.search(body))


def _fingerprint(regulation: str, section_ref: str, category: str, quote: str) -> str:
    norm = re.sub(r"\s+", " ", quote).strip().lower()
    return hashlib.sha256(f"{regulation}|{section_ref}|{category}|{norm}".encode()).hexdigest()


def ingest_document(session: Session, document_id: uuid.UUID, storage: Storage, engine: Engine,
                    embedder: Embedder, max_workers: int = 4) -> IngestResult:
    doc = session.get(Document, document_id)
    assert doc is not None
    text = to_text(storage.get(doc.raw_path), doc.content_type)
    prev = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                          .order_by(DocumentVersion.version.desc()).limit(1))
    version = (prev.version if prev else 0) + 1
    diff = ""
    if prev:
        diff = "\n".join(difflib.unified_diff(prev.text.splitlines(), text.splitlines(),
                                              f"v{prev.version}", f"v{version}", lineterm=""))
    session.add(DocumentVersion(document_id=doc.id, version=version, content_hash=doc.content_hash,
                                text=text, diff=diff or None))
    result = IngestResult(document_id=doc.id, version=version, diff=diff)

    chunks = chunk_text(text, doc.regulation)
    active = {c.text_hash: c for c in session.scalars(
        select(RegChunk).where(RegChunk.document_id == doc.id, RegChunk.active.is_(True)))}
    incoming = {c.text_hash: c for c in chunks}

    # Retire chunks that disappeared, and their obligations.
    for h, old in active.items():
        if h not in incoming:
            old.active = False
            result.retired_chunks += 1
            retired = session.scalars(select(Obligation.id).where(Obligation.chunk_id == old.id,
                                                                  Obligation.active.is_(True)))
            result.retired_obligation_ids.extend(retired)
            session.execute(update(Obligation).where(Obligation.chunk_id == old.id)
                            .values(active=False))
    for h in active.keys() & incoming.keys():
        active[h].version = version

    new_chunks: list[Chunk] = [c for h, c in incoming.items() if h not in active]
    if new_chunks:
        vectors = embedder.embed_documents(
            [f"{c.context}\n{c.heading}\n{c.text}".strip() for c in new_chunks], "law")
        rows = []
        for c, vec in zip(new_chunks, vectors, strict=True):
            row = RegChunk(document_id=doc.id, version=version, regulation=doc.regulation,
                           section_ref=c.section_ref, heading=c.heading, text=c.text,
                           context=c.context, text_hash=c.text_hash, embedding=vec)
            session.add(row)
            rows.append(row)
        session.flush()
        result.new_chunks = len(rows)

        def extract(c: Chunk) -> list[ObligationDraft]:
            if not worth_extracting(c, doc.regulation):
                return []
            body = f"{c.context}\n{c.text}".strip()
            return engine.extract_obligations(doc.regulation, c.section_ref, c.heading, body)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            drafts_per_chunk = list(pool.map(extract, new_chunks))

        existing_fps = set(session.scalars(select(Obligation.fingerprint).where(
            Obligation.document_id == doc.id, Obligation.active.is_(True))))
        for row, drafts in zip(rows, drafts_per_chunk, strict=True):
            for d in drafts:
                fp = _fingerprint(doc.regulation, row.section_ref, d.category, d.quote)
                if fp in existing_fps:
                    continue
                existing_fps.add(fp)
                ob = Obligation(chunk_id=row.id, document_id=doc.id, regulation=doc.regulation,
                                section_ref=row.section_ref, source_url=doc.url, actor=d.actor,
                                action=d.action, condition=d.condition, category=d.category,
                                severity=d.severity, code_checkable=d.code_checkable,
                                summary=d.summary, quote=d.quote, fingerprint=fp)
                session.add(ob)
                session.flush()
                result.new_obligation_ids.append(ob.id)

    doc.current_version, doc.status = version, "ingested"
    session.flush()
    log.info("Ingested %s v%s: %s new chunks, %s retired, %s new obligations", doc.external_id,
             version, result.new_chunks, result.retired_chunks, len(result.new_obligation_ids))
    return result
