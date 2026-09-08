"""Typed application contracts for managed specification execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecCompletionStatus,
    ManagedSpecPrepareStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecIdentity:
    """Exact canonical specification selector.

    A managed specification is selected by its stable note id only.  Paths and
    titles are deliberately absent so callers cannot silently substitute a
    similarly named prompt.
    """

    note_id: str

    def __post_init__(self) -> None:
        """Reject an empty exact selector before any source read."""
        if not self.note_id.strip():
            raise ValueError("managed specification note_id is required")


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecExecutionContext:
    """Typed scheduler context trusted by the managed-spec boundary."""

    project: str
    workflow: str
    entity: str
    edition: str | None = None
    expected_policy_note_id: str

    def __post_init__(self) -> None:
        """Require every identity component needed for output ownership."""
        values = (
            ("project", self.project),
            ("workflow", self.workflow),
            ("entity", self.entity),
            ("expected_policy_note_id", self.expected_policy_note_id),
        )
        for name, value in values:
            if not value.strip():
                raise ValueError(f"{name} is required")
        if self.edition is not None and not self.edition.strip():
            raise ValueError("edition must be non-empty when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecPrepareRequest:
    """Prepare one exact managed specification for a logical execution."""

    spec_identity: ManagedSpecIdentity
    logical_date: str
    idempotency_key: str
    execution_context: ManagedSpecExecutionContext

    def __post_init__(self) -> None:
        """Reject empty idempotency and date inputs at the domain boundary."""
        if not self.logical_date.strip():
            raise ValueError("logical_date is required")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecCompleteRequest:
    """Complete a previously persisted envelope with caller-owned output data."""

    idempotency_key: str
    prepared_envelope_hash: str
    output_title: str
    output_body: str
    expected_output_content_hash: str | None = None

    def __post_init__(self) -> None:
        """Reject empty completion identity and output content."""
        values = (
            ("idempotency_key", self.idempotency_key),
            ("prepared_envelope_hash", self.prepared_envelope_hash),
            ("output_title", self.output_title),
            ("output_body", self.output_body),
        )
        for name, value in values:
            if not value.strip():
                raise ValueError(f"{name} is required")


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecOutputWrite:
    """Typed output mutation delegated to the canonical verified-upsert owner."""

    idempotency_key: str
    logical_identity: ObsidianLogicalIdentity
    title: str
    body: str
    spec_note_id: str
    spec_version: int
    spec_content_hash: str
    policy_note_id: str
    policy_version: int
    policy_content_hash: str
    prepared_envelope_hash: str
    expected_content_hash: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecOutputWriteResult:
    """Bounded verified-upsert result exposed by managed-spec completion."""

    operation: str
    note_id: str
    canonical_path: str
    logical_identity: ObsidianLogicalIdentity
    content_hash: str
    storage_durable: bool
    readback_verified: bool
    metadata_status: str
    fts_status: str
    vector_status: str
    graph_edge_index_status: str
    graph_projection_status: str
    duplicate_safe: bool
    warnings: tuple[str, ...] = ()


class ManagedSpecCheckpointStore(Protocol):
    """Durable typed checkpoint authority backed by report-bundle run storage."""

    async def load(self, idempotency_key: str) -> ManagedSpecCheckpoint | None:
        """Load one checkpoint by its caller-provided idempotency key."""

    async def save_if_absent(
        self,
        checkpoint: ManagedSpecCheckpoint,
    ) -> bool:
        """Persist once and return false when another value already exists."""

    async def save(self, checkpoint: ManagedSpecCheckpoint) -> None:
        """Persist an already-owned checkpoint update durably."""


class ManagedSpecOutputWriter(Protocol):
    """Canonical verified-upsert port owned by the note-write implementation."""

    async def verified_upsert(
        self,
        request: ManagedSpecOutputWrite,
    ) -> ManagedSpecOutputWriteResult:
        """Persist and read back one logical managed-spec output."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecEnvelope:
    """Inert reference-only trust envelope pinned to exact source revisions."""

    idempotency_key: str
    spec_identity: ManagedSpecIdentity
    logical_identity: ObsidianLogicalIdentity
    policy_note_id: str
    policy_version: int
    policy_content_hash: str
    policy_body: str
    spec_version: int
    spec_content_hash: str
    spec_body: str
    allowed_workflow: str
    reference_only: bool = True
    may_expand_permissions: bool = False
    may_start_unrelated_work: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecCheckpoint:
    """Durable prepare/complete state for one logical execution attempt."""

    idempotency_key: str
    prepare_request_hash: str
    envelope_hash: str
    envelope: ManagedSpecEnvelope
    output_request: ManagedSpecOutputWrite | None = None
    completion_request_hash: str | None = None
    output: ManagedSpecOutputWriteResult | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecPrepareResult:
    """Typed result returned after an envelope is prepared or replayed."""

    status: ManagedSpecPrepareStatus
    envelope: ManagedSpecEnvelope
    envelope_hash: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedSpecCompleteResult:
    """Typed result returned after one output is durably completed or replayed."""

    status: ManagedSpecCompletionStatus
    envelope: ManagedSpecEnvelope
    envelope_hash: str
    output: ManagedSpecOutputWriteResult
