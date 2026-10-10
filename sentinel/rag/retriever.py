"""Hybrid retrieval: pgvector cosine search + Postgres full-text search, merged by reciprocal rank
fusion (RRF), then an optional Voyage rerank."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, case, func, select
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


def rrf_merge(rankings: list[list[uuid.UUID]], weights: list[float] | None = None,
              k: int = RRF_K) -> dict[uuid.UUID, float]:
    """Weighted reciprocal rank fusion: score = sum of weight / (k + rank)."""
    weights = weights or [1.0] * len(rankings)
    scores: dict[uuid.UUID, float] = {}
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + w / (k + rank + 1)
    return scores


def _hybrid(session: Session, model, base: Select, query: str, qvec: list[float],
            ts_config: str, k: int, pool: int, vector_weight: float = 1.0) -> list[Hit]:
    vec_ids = list(session.scalars(
        base.with_only_columns(model.id).order_by(model.embedding.cosine_distance(qvec)).limit(pool)))
    kw_ids = _keyword_ids(session, model, base, query, ts_config, pool)
    fused = rrf_merge([vec_ids, kw_ids], [vector_weight, 1.0])
    top = sorted(fused, key=fused.__getitem__, reverse=True)[:k]
    rows = {r.id: r for r in session.scalars(select(model).where(model.id.in_(top)))}
    return [Hit(id=i, score=fused[i], row=rows[i]) for i in top if i in rows]


def _keyword_ids(session: Session, model, base: Select, query: str, ts_config: str,
                 pool: int) -> list[uuid.UUID]:
    """IDF-weighted keyword ranking. Postgres has no BM25, so each query lexeme is weighted by how
    rare it is in the candidate set, and ts_rank_cd breaks ties."""
    lexemes = session.scalar(select(func.array(
        select(func.unnest(func.tsvector_to_array(func.to_tsvector(ts_config, query))))
        .scalar_subquery()))) or []
    if not lexemes:
        return []
    total = session.scalar(base.with_only_columns(func.count())) or 1
    score = None
    for lex in lexemes:
        term = func.to_tsquery(ts_config, func.quote_literal(lex))
        df = session.scalar(base.with_only_columns(func.count()).where(model.tsv.op("@@")(term)))
        if not df:
            continue
        idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
        part = case((model.tsv.op("@@")(term), idf), else_=0.0)
        score = part if score is None else score + part
    if score is None:
        return []
    any_q = func.to_tsquery(ts_config, " | ".join(f"'{lex}'" for lex in lexemes))
    return list(session.scalars(
        base.with_only_columns(model.id).where(model.tsv.op("@@")(any_q))
        .order_by(score.desc(), func.ts_rank_cd(model.tsv, any_q, 32).desc()).limit(pool)))


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
                   "english", k * 4, max(20, k * 4), getattr(embedder, "vector_weight", 1.0))
    return _rerank(settings, query, hits, lambda r: f"{r.section_ref} {r.text}", k)


def search_code(session: Session, embedder: Embedder, repo_id: uuid.UUID, commit: str,
                query: str, k: int = 8, settings: Settings | None = None) -> list[Hit]:
    settings = settings or get_settings()
    base = select(CodeChunk).where(CodeChunk.repo_id == repo_id, CodeChunk.commit == commit)
    hits = _hybrid(session, CodeChunk, base, query, embedder.embed_query(query, "code"),
                   "simple", k * 3, max(20, k * 3), getattr(embedder, "vector_weight", 1.0))
    return _rerank(settings, query, hits, lambda r: f"{r.path} {r.symbol}\n{r.text}", k)
