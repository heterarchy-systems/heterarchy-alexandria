"""Validated Context identity models restored from Obsidian frontmatter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.memory.domain.event_enum.context_enums import (
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianContextLifecycleStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianContextProvenance:
    """Validated generalized provenance restored from Context frontmatter."""

    source_actor_id: str | None
    source_actor_type: ContextSourceType | None
    source_run_id: str | None
    external_run_id: str | None
    artifact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    confidence: ContextImportance | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianContextIdentity:
    """Validated identity fields restored from Context frontmatter."""

    scope: ContextScope
    project: str | None
    workspace_id: str | None
    agent_id: str | None
    user_id: str | None
    session_id: str | None
    visibility: ContextScope
    status: ObsidianContextLifecycleStatus
    provenance: ObsidianContextProvenance
    content_hash: str
    version: int
    supersedes_context_id: str | None
    superseded_by_context_id: str | None
    context_kind: ContextKind
    created_at: datetime | None
    updated_at: datetime | None
    recorded_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    reconciliation_candidate_id: str | None = None
    conflict_set_ids: tuple[str, ...] = ()
