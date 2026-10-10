"""Run-scoped dependencies passed to graph nodes through LangGraph's runtime context.

They are not part of graph state, so they are never written into checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.config import Settings, get_settings
from sentinel.embeddings import Embedder, get_embedder
from sentinel.llm import Engine, get_engine
from sentinel.notify.notifier import Notifier
from sentinel.storage import Storage


@dataclass
class AgentContext:
    settings: Settings = field(default_factory=get_settings)
    engine: Engine = field(default_factory=get_engine)
    embedder: Embedder = field(default_factory=get_embedder)
    storage: Storage = field(default_factory=Storage)
    notifier: Notifier = field(default_factory=Notifier)
    database_url: str | None = None
