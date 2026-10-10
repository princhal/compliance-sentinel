"""Hybrid retrieval: pgvector cosine search + Postgres full-text search, merged by reciprocal rank
fusion (RRF), then an optional Voyage rerank."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, Text, func, select
from sqlalchemy.orm import Session

from sentinel.config import Settings, get_settings
from sentinel.db.models import CodeChunk, RegChunk
from sentinel.embeddings import Embedder

RRF_K = 60


@dataclass
class Hit:
    id: uuid.UUID
    score: float
    row: object


def rrf_merge(*rankings: list[uuid.UUID], k: int = RRF_K) -> dict[uuid.UUID, float]:
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _hybrid(session: Session, model, base: Select, query: str, qvec: list[float],
            ts_config: str, k: int, pool: int) -> list[Hit]:
    vec_ids = list(session.scalars(
        base.with_only_columns(model.id).order_by(model.embedding.cosine_distance(qvec)).limit(pool)))
    tsq = func.websearch_to_tsquery(ts_config, query)
    # OR the query terms together so partial matches still rank.
    or_tsq = func.to_tsquery(ts_config, func.replace(func.plainto_tsquery(ts_config, query).cast(
        Text), "&", "|"))
    kw_ids = list(session.scalars(
        base.with_only_columns(model.id).where(model.tsv.op("@@")(or_tsq))
        .order_by(func.ts_rank_cd(model.tsv, or_tsq).desc(), func.ts_rank_cd(model.tsv, tsq).desc())
        .limit(pool)))
    fused = rrf_merge(vec_ids, kw_ids)
    top = sorted(fused, key=fused.__getitem__, reverse=True)[:k]
    rows = {r.id: r for r in session.scalars(select(model).where(model.id.in_(top)))}
    return [Hit(id=i, score=fused[i], row=rows[i]) for i in top if i in rows]


def _rerank(settings: Settings, query: str, hits: list[Hit], text_of, k: int) -> list[Hit]:
    if not settings.use_voyage or len(hits) <= 1:
        return hits[:k]
    import voyageai

    client = voyageai.Client(api_key=settings.voyage_api_key or None)
    res = client.rerank(query, [text_of(h.row) for h in hits], model=settings.rerank_model,
                        top_k=k)
    return [Hit(id=hits[r.index].id, score=r.relevance_score, row=hits[r.index].row)
            for r in res.results]


def search_regulations(session: Session, embedder: Embedder, query: str, k: int = 5,
                       regulation: str | None = None,
                       settings: Settings | None = None) -> list[Hit]:
    settings = settings or get_settings()
    base = select(RegChunk).where(RegChunk.active.is_(True))
    if regulation:
        base = base.where(RegChunk.regulation == regulation)
    hits = _hybrid(session, RegChunk, base, query, embedder.embed_query(query, "law"),
                   "english", k * 4, max(20, k * 4))
    return _rerank(settings, query, hits, lambda r: f"{r.section_ref} {r.text}", k)


def search_code(session: Session, embedder: Embedder, repo_id: uuid.UUID, commit: str,
                query: str, k: int = 8, settings: Settings | None = None) -> list[Hit]:
    settings = settings or get_settings()
    base = select(CodeChunk).where(CodeChunk.repo_id == repo_id, CodeChunk.commit == commit)
    hits = _hybrid(session, CodeChunk, base, query, embedder.embed_query(query, "code"),
                   "simple", k * 3, max(20, k * 3))
    return _rerank(settings, query, hits, lambda r: f"{r.path} {r.symbol}\n{r.text}", k)
