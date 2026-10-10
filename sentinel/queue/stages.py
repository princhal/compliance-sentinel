"""Pipeline stages as plain functions. Queue workers and the CLI both call these."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from sentinel.db.models import Repo, Source
from sentinel.db.session import session_scope
from sentinel.embeddings import get_embedder
from sentinel.ingest.pipeline import ensure_sources, ingest_document, scrape_source
from sentinel.llm import get_engine
from sentinel.storage import Storage

log = logging.getLogger(__name__)


def scrape(source_keys: list[str] | None = None,
           override: dict[str, Any] | None = None) -> list[str]:
    """Returns IDs of documents that are new or changed."""
    storage = Storage()
    changed: list[str] = []
    with session_scope() as s:
        ensure_sources(s)
        q = select(Source)
        q = q.where(Source.key.in_(source_keys)) if source_keys else q.where(Source.enabled.is_(True))
        for source in s.scalars(q):
            res = scrape_source(s, source, storage, override if source.kind == "fixture" else None)
            changed.extend(str(d) for d in res.changed_document_ids)
    return changed


def ingest(document_ids: list[str]) -> list[str]:
    """Returns IDs of new obligations."""
    storage, engine, embedder = Storage(), get_engine(), get_embedder()
    new: list[str] = []
    for doc_id in document_ids:
        with session_scope() as s:
            res = ingest_document(s, uuid.UUID(doc_id), storage, engine, embedder)
            new.extend(str(o) for o in res.new_obligation_ids)
    return new


def repos_to_reaudit() -> list[tuple[str, str]]:
    with session_scope() as s:
        return [(str(r.org_id), str(r.id)) for r in s.scalars(select(Repo))]


def scrape_and_ingest(source_keys: list[str] | None = None,
                      override: dict[str, Any] | None = None) -> dict[str, Any]:
    docs = scrape(source_keys, override)
    obligations = ingest(docs) if docs else []
    return {"changed_documents": docs, "new_obligations": obligations}
