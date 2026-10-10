"""Embedding providers. Voyage in production; a deterministic hashing embedder offline and in tests."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Literal, Protocol

from sentinel.config import EMBEDDING_DIM, Settings, get_settings

Kind = Literal["law", "code"]
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|\d+")


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str], kind: Kind) -> list[list[float]]: ...
    def embed_query(self, text: str, kind: Kind) -> list[float]: ...


def _tokens(text: str) -> list[str]:
    words: list[str] = []
    for tok in _TOKEN.findall(text):
        low = tok.lower()
        words.append(low)
        # Split snake_case and camelCase so "user_email" matches "email".
        parts = [p for p in re.split(r"_|(?<=[a-z])(?=[A-Z])", tok) if p]
        if len(parts) > 1:
            words.extend(p.lower() for p in parts)
    return words


class HashEmbedder:
    """Feature-hashed bag of words and bigrams. No network, stable across runs."""

    name = "hash-1024"

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        toks = _tokens(text)
        grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]
        for g in grams:
            h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
            vec[h % EMBEDDING_DIM] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str], kind: Kind) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str, kind: Kind) -> list[float]:
        return self._vec(text)


class VoyageEmbedder:
    """voyage-law-2 for regulations, voyage-code-3 for code. Both return 1024 dimensions."""

    def __init__(self, settings: Settings) -> None:
        import voyageai

        self.client = voyageai.Client(api_key=settings.voyage_api_key or None)
        self.models = {"law": settings.voyage_law_model, "code": settings.voyage_code_model}
        self.name = f"voyage:{self.models['law']}+{self.models['code']}"

    def embed_documents(self, texts: list[str], kind: Kind) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            res = self.client.embed(texts[i : i + 64], model=self.models[kind],
                                    input_type="document")
            out.extend(res.embeddings)
        return out

    def embed_query(self, text: str, kind: Kind) -> list[float]:
        return self.client.embed([text], model=self.models[kind], input_type="query").embeddings[0]


def get_embedder(settings: Settings | None = None) -> Embedder:
    settings = settings or get_settings()
    return VoyageEmbedder(settings) if settings.use_voyage else HashEmbedder()
