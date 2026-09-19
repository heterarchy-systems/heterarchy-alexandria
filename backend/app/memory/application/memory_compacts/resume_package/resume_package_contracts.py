"""Typed contracts for versioned resume context packages.

A resume package is a sealed Memory Compact artifact (``ContextKind`` HANDOFF
semantics stored through the compact path) that carries the structured state a
worker handoff needs: goal, attributed accepted changes and constraints,
verified versus unverified status, blockers, the single next action, observed
evidence references, and lineage. The package is data only: it stores and
retrieves observed context, and it never grants execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumePackageAttributedItem:
    """One accepted change or constraint with its evidence attribution."""

    text: str
    source_context_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumePackageEvidenceRef:
    """Server-observed evidence backing one resume package.

    Every field is observed from the stored Context record at seal time; the
    content hash is computed over the observed content and is never caller
    supplied.
    """

    context_id: str
    content_hash: str
    source: str
    created_at: datetime
    observed_updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumePackageLineage:
    """Worker-handoff lineage identity for one resume package.

    ``previous_package_id`` and ``package_revision`` are sealed by the assembly
    service; draft input must leave them unset.
    """

    lineage_id: str
    worker_id: str | None = None
    run_id: str | None = None
    workspace_id: str | None = None
    session_id: str | None = None
    previous_package_id: str | None = None
    package_revision: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumePackageDraft:
    """Caller-supplied content for one resume package.

    Evidence is addressed by stored Context identifiers; the assembly service
    resolves them into observed :class:`ResumePackageEvidenceRef` values.
    ``request_id`` is an optional caller retry-fencing identity: retrying the
    same request id with changed content is rejected instead of sealed as a
    new revision.
    """

    project: str | None
    goal: str
    summary: str
    current_state: str
    next_single_action: str
    covered_from: datetime
    covered_to: datetime
    lineage: ResumePackageLineage
    evidence_context_ids: tuple[str, ...]
    accepted_changes: tuple[ResumePackageAttributedItem, ...] = ()
    constraints: tuple[ResumePackageAttributedItem, ...] = ()
    verified_complete: tuple[str, ...] = ()
    implemented_unverified: tuple[str, ...] = ()
    unfinished_tasks: tuple[str, ...] = ()
    uncertain_results: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    request_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumePackageSeal:
    """Sealed identity returned when a resume package is created or reused."""

    package_id: str
    package_revision: int
    previous_package_id: str | None
    draft_hash: str
    deduplicated: bool
    source_set_hash: str | None
    compaction_policy_version: str | None
    generated_at: datetime | None
    markdown_body: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumePackageView:
    """Reopened structured view of one stored resume package."""

    package_id: str
    project: str | None
    status: MemoryCompactStatus
    covered_from: datetime
    covered_to: datetime
    goal: str
    summary: str
    current_state: str
    next_single_action: str
    accepted_changes: tuple[ResumePackageAttributedItem, ...]
    constraints: tuple[ResumePackageAttributedItem, ...]
    verified_complete: tuple[str, ...]
    implemented_unverified: tuple[str, ...]
    unfinished_tasks: tuple[str, ...]
    uncertain_results: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence_refs: tuple[ResumePackageEvidenceRef, ...]
    lineage: ResumePackageLineage
    draft_hash: str
    source_set_hash: str | None
    compaction_policy_version: str | None
    compact_generation_revision: int | None
    generated_at: datetime | None
    deduplicated: bool
    markdown_body: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumePackageLineageEntry:
    """One stored package observed during a lineage revision scan."""

    package_id: str
    package_revision: int
    draft_hash: str
    updated_at: datetime
    request_id: str | None = None


# protocol-contract: structural-seam
class ResumePackageEvidenceSource(Protocol):
    """Minimal Context read seam required to seal observed evidence."""

    async def get(self, context_id: str) -> ContextRecord:
        """Return one stored Context record or raise not-found.

        Args:
            context_id: Stored Context identifier.

        Returns:
            Observed Context read model.
        """
        ...
