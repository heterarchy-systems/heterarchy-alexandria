"""Durable mutation outcome evidence for one fenced logical write."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)

MutationOperationKind = Literal["verified_upsert", "relate", "note_write"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianMutationOutcome:
    """Truthful retry-safety verdict assembled from durable fence evidence."""

    operation: MutationOperationKind
    idempotency_key: str | None
    status: ObsidianMutationOutcomeStatus
    checkpoint_state: str | None = None
    canonical_path: str | None = None
    note_id: str | None = None
    content_hash: str | None = None
    version: int | None = None
    evidence: tuple[str, ...] = ()
    mutation_id: str | None = None
    operation_identity: str | None = None
    committed_at: datetime | None = None
    error_summary: str | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class NoteMutationReceipt:
    """Durable admission and exact source evidence for an ordinary note write."""

    idempotency_key: str
    mutation_id: str
    operation_identity: str
    status: ObsidianMutationOutcomeStatus
    effect_started: bool = False
    canonical_path: str | None = None
    note_id: str | None = None
    expected_source_hash: str | None = None
    previous_source_hash: str | None = None
    content_hash: str | None = None
    version: int | None = None
    committed_at: datetime | None = None
    error_summary: str | None = None
