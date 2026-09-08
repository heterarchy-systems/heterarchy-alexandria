"""Typed contracts for the high-level agent-facing recall operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
)
from app.memory.domain.event_enum.recall_enums import RecallScopeMode
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RecallExactSelector:
    """Optional canonical selector used before retrieval-index search."""

    note_id: str | None = None
    path: str | None = None
    logical_identity: ObsidianLogicalIdentity | None = None

    def __post_init__(self) -> None:
        """Require exactly one concrete canonical selector."""
        selected = sum(
            (
                self.note_id is not None and bool(self.note_id.strip()),
                self.path is not None and bool(self.path.strip()),
                self.logical_identity is not None,
            )
        )
        if selected != 1:
            raise ValueError(
                "exact selector requires exactly one of note_id, path, or logical_identity"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecallRequest:
    """Validated internal request for one bounded high-level recall."""

    query: str
    limit: int = 5
    scope_mode: RecallScopeMode = RecallScopeMode.AUTO
    include_scopes: tuple[ContextScope, ...] = ()
    project: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    related_projects: tuple[str, ...] = ()
    selector: RecallExactSelector | None = None
    as_of: datetime | None = None
    kind: ContextKind | None = None
    include_lifecycle_statuses: tuple[ContextRecallLifecycleStatus, ...] = ()


class RecallExactSelectorResolver(Protocol):
    """Resolve exact selectors through the canonical source-read authority."""

    async def resolve(
        self,
        selector: RecallExactSelector,
        scope_identity: ScopeIdentity,
    ) -> tuple[ContextSearchMatch, ...]:
        """Return source-backed exact matches inside the validated scope."""
