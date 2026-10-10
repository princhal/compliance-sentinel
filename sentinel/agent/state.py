"""Graph state. Everything here is JSON-serializable so the Postgres checkpointer can store it."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AuditState(TypedDict, total=False):
    run_id: str
    org_id: str
    repo_id: str
    obligation_ids: list[str] | None  # Set for re-audits after a regulation change.
    workdir: str
    commit: str
    obligations: list[dict[str, Any]]
    static_hits: list[dict[str, Any]]
    findings: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    alertable: int
    approval: dict[str, Any] | None
    report_id: str | None


class GroupInput(TypedDict):
    """Input for one parallel check: all obligations in one category, plus its evidence."""

    category: str
    obligations: list[dict[str, Any]]
    hits: list[dict[str, Any]]
    repo_id: str
    commit: str
    workdir: str


class GroupState(GroupInput, total=False):
    queries: list[str]
    evidence: list[dict[str, Any]]
    assessed: list[dict[str, Any]]
    findings: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]


class GroupOutput(TypedDict, total=False):
    findings: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
