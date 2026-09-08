"""Typed outcomes and durable checkpoints for Obsidian relations."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianRelationType,
    ObsidianWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianRelateIssue:
    """Actionable, bounded issue evidence returned by relation verification."""

    code: str
    cause: str
    affected_capability: str
    retryable: bool
    safe_next_action: str
    recovery_run_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianRelateResult:
    """Truthful source, index, projection, and readback evidence."""

    completion_status: ObsidianRelateCompletionStatus
    idempotency_key: str
    replayed: bool
    source_note_id: str
    target_note_id: str
    relation: ObsidianRelationType
    source_path: str
    target_path: str
    operation: ObsidianWriteOperation | None
    content_hash: str
    storage_status: str
    metadata_status: str
    fts_status: str
    graph_edge_index_status: str
    graph_projection_status: str
    source_link_verified: bool
    target_backlink_verified: bool
    related_notes_verified: bool
    graph_edge_id: str | None = None
    projection_run_id: str | None = None
    warnings: tuple[ObsidianRelateIssue, ...] = field(default_factory=tuple)
    errors: tuple[ObsidianRelateIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianRelateCheckpoint:
    """Immutable request intent and last verified outcome for one replay key."""

    request_hash: str
    source_note_id: str
    target_note_id: str
    relation: ObsidianRelationType
    source_content_hash: str
    result: ObsidianRelateResult
