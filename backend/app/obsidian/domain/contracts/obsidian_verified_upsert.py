"""Typed contracts for the agent-facing verified Obsidian upsert."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.memory.domain.types.context_payload_types import ContextProvenancePayload
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType


class ObsidianVerifiedUpsertOperation(StrEnum):
    """Observed logical operation for one verified upsert."""

    CREATED = "created"
    UPDATED = "updated"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class ObsidianVerifiedProjectionStatus(StrEnum):
    """Evidence status for one source or derived projection."""

    UNKNOWN = "unknown"
    PENDING = "pending"
    STALE = "stale"
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"


class ObsidianVerifiedDuplicateSafety(StrEnum):
    """Logical-identity duplicate safety evidence."""

    VERIFIED = "verified"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class ObsidianVerifiedCheckpointState(StrEnum):
    """Durable phases used to recover a verified upsert after interruption."""

    INTENT_RECORDED = "intent_recorded"
    WRITE_STARTED = "write_started"
    COMPLETED = "completed"
    UNKNOWN_OUTCOME = "unknown_outcome"


def _empty_provenance() -> ContextProvenancePayload:
    """Return the explicit empty provenance payload for agent writes."""
    return {
        "source_actor_id": None,
        "source_actor_type": None,
        "source_run_id": None,
        "external_run_id": None,
        "artifact_refs": [],
        "evidence_refs": [],
        "confidence": None,
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVerifiedUpsertRequest:
    """Validated internal command for one logical note write."""

    identity: ObsidianLogicalIdentity
    title: str
    body: str
    alexandria_type: AlexandriaNoteType
    idempotency_key: str
    expected_content_hash: str | None = None
    tags: tuple[str, ...] = ()
    provenance: ContextProvenancePayload = field(default_factory=_empty_provenance)
    source: str = "agent"

    def __post_init__(self) -> None:
        """Normalize the collections and reject blank command identity."""
        if not self.title.strip():
            raise ValueError("verified upsert title is required")
        if not self.idempotency_key.strip():
            raise ValueError("verified upsert idempotency_key is required")
        if not self.source.strip():
            raise ValueError("verified upsert source is required")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVerifiedUpsertResult:
    """Truthful source, readback, and projection evidence for one upsert."""

    operation: ObsidianVerifiedUpsertOperation
    idempotency_key: str
    logical_identity: ObsidianLogicalIdentity
    note_id: str
    canonical_path: str
    content_hash: str
    version: int | None
    storage_status: ObsidianVerifiedProjectionStatus
    readback_verified: bool
    metadata_status: ObsidianVerifiedProjectionStatus
    fts_status: ObsidianVerifiedProjectionStatus
    vector_status: ObsidianVerifiedProjectionStatus
    graph_edge_index_status: ObsidianVerifiedProjectionStatus
    graph_projection_status: ObsidianVerifiedProjectionStatus
    duplicate_safety: ObsidianVerifiedDuplicateSafety
    warnings: tuple[str, ...] = ()
    error_code: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVerifiedUpsertSelector:
    """Canonical selector accepted by the logical-note verification composite."""

    identity: ObsidianLogicalIdentity | None = None
    note_id: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        """Require one concrete canonical selector."""
        selectors = tuple(value for value in (self.note_id, self.path) if value)
        if self.identity is None and not selectors:
            raise ValueError(
                "verified upsert selector requires identity, note_id, or path"
            )
        if self.identity is not None and selectors:
            raise ValueError("verified upsert selector accepts one selector")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVerifiedUpsertVerification:
    """Composite diagnosis for one logical or exact note selector."""

    source_readable: bool
    canonical_identity_resolved: bool
    indexed: bool
    vector_current: bool | None
    graph_current: bool | None
    duplicate_safe: bool | None
    temporal_authority_consistent: bool | None
    note_id: str | None
    canonical_path: str | None
    content_hash: str | None
    version: int | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVerifiedUpsertCheckpoint:
    """Credential-free durable intent/result fence for one upsert."""

    state: ObsidianVerifiedCheckpointState
    request_hash: str
    logical_identity: ObsidianLogicalIdentity
    canonical_path: str
    title: str
    body_hash: str
    expected_content_hash: str | None
    note_id: str | None = None
    target_note_id: str | None = None
    content_hash: str | None = None
    version: int | None = None
    warnings: tuple[str, ...] = ()
