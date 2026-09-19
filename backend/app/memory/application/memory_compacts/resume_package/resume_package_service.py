"""Versioned resume context package application service.

The service seals worker-handoff packages as Memory Compact artifacts through
the existing compact creation path (signature dedupe, quality review, and the
project CURRENT supersede lifecycle). It stores and retrieves observed
context only; a package is data and grants no execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.memory_compacts.resume_package.resume_package_assembly import (
    ValidatedResumePackage,
    next_lineage_successor,
    validated_resume_package,
)
from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageDraft,
    ResumePackageEvidenceRef,
    ResumePackageEvidenceSource,
    ResumePackageLineage,
    ResumePackageLineageEntry,
    ResumePackageSeal,
    ResumePackageView,
)
from app.memory.application.memory_compacts.resume_package.resume_package_markdown import (
    parse_resume_package_markdown,
    render_resume_package_markdown,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryResumePackageEvidenceNotFoundError,
    MemoryResumePackageRequestConflictError,
    MemoryResumePackageValidationError,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextNotFoundError

_CONTEXT_SOURCE_TYPE = "CONTEXT"
_CONTEXT_DETAIL_PATH_PREFIX = "/memory/contexts/"


@dataclass(frozen=True, slots=True, kw_only=True)
class _ObservedEvidence:
    """Evidence resolved from stored Contexts for one draft."""

    refs: tuple[ResumePackageEvidenceRef, ...]
    titles_by_context_id: dict[str, str]


class MemoryResumePackageService:
    """Assemble, seal, and reopen versioned resume context packages."""

    def __init__(
        self,
        compact_service: MemoryCompactService,
        evidence_source: ResumePackageEvidenceSource,
    ) -> None:
        """Create the resume package service.

        Args:
            compact_service: Stable Memory Compact application facade used for
                durable storage, lifecycle, and reads.
            evidence_source: Structural Context read seam used to observe
                evidence referenced by a draft.
        """
        self._compact_service = compact_service
        self._evidence_source = evidence_source

    async def create_resume_package(
        self,
        draft: ResumePackageDraft,
    ) -> ResumePackageSeal:
        """Assemble, seal, and durably store one resume package.

        Evidence references are validated against stored Contexts first, so a
        missing reference raises a typed error before anything is persisted.
        The whole lineage critical section (revision scan, duplicate check,
        retry-fencing check, next-revision selection, creation with the
        CURRENT supersede, and durable read-back) runs under the cross-process
        compact creation guard, so concurrent same-lineage writers cannot race
        revisions; the inner compact creation re-enters the same task-local
        lock acquisition. An identical draft (same content and same observed
        evidence) on the same lineage returns the existing package with
        ``deduplicated=True`` and no revision bump. A stored request id that
        is retried with different content raises the typed request-conflict
        error. New content seals the next monotonic revision for the lineage
        and supersedes the previous project CURRENT package through the
        compact creation lifecycle.

        Args:
            draft: Caller-supplied resume package draft.

        Returns:
            Sealed package identity and provenance.

        Raises:
            MemoryResumePackageRequestConflictError: When the draft reuses a
                sealed request id with different content.
        """
        evidence = await self._collect_evidence(draft.evidence_context_ids)
        validated = validated_resume_package(draft, evidence.refs)
        async with self._compact_service.creation_guard():
            lineage_entries = await self._lineage_entries(
                validated.draft.lineage.lineage_id,
                validated.draft.project,
            )
            existing = next(
                (
                    entry
                    for entry in lineage_entries
                    if entry.draft_hash == validated.draft_hash
                ),
                None,
            )
            if existing is not None:
                return await self._seal_from_stored(
                    existing.package_id,
                    deduplicated=True,
                )
            _reject_request_id_conflict(lineage_entries, validated)
            package_revision, previous_package_id = next_lineage_successor(
                lineage_entries
            )
            markdown_body = render_resume_package_markdown(
                project=validated.draft.project,
                goal=validated.draft.goal,
                summary=validated.draft.summary,
                current_state=validated.draft.current_state,
                next_single_action=validated.draft.next_single_action,
                covered_from=validated.draft.covered_from,
                covered_to=validated.draft.covered_to,
                accepted_changes=validated.draft.accepted_changes,
                constraints=validated.draft.constraints,
                verified_complete=validated.draft.verified_complete,
                implemented_unverified=validated.draft.implemented_unverified,
                unfinished_tasks=validated.draft.unfinished_tasks,
                uncertain_results=validated.draft.uncertain_results,
                blockers=validated.draft.blockers,
                evidence_refs=validated.evidence_refs,
                lineage_id=validated.draft.lineage.lineage_id,
                worker_id=validated.draft.lineage.worker_id,
                run_id=validated.draft.lineage.run_id,
                workspace_id=validated.draft.lineage.workspace_id,
                session_id=validated.draft.lineage.session_id,
                previous_package_id=previous_package_id,
                package_revision=package_revision,
                draft_hash=validated.draft_hash,
                request_id=validated.draft.request_id,
            )
            compact = await self._compact_service.create(
                MemoryCompactCreate(
                    project=validated.draft.project,
                    covered_from=validated.draft.covered_from,
                    covered_to=validated.draft.covered_to,
                    markdown_body=markdown_body,
                    status=MemoryCompactStatus.CURRENT,
                    source_refs=tuple(
                        MemoryCompactSourceRefCreate(
                            source_type=_CONTEXT_SOURCE_TYPE,
                            source_id=evidence_ref.context_id,
                            title=evidence.titles_by_context_id[
                                evidence_ref.context_id
                            ],
                            detail_path=(
                                f"{_CONTEXT_DETAIL_PATH_PREFIX}{evidence_ref.context_id}"
                            ),
                            source_hash=evidence_ref.content_hash,
                        )
                        for evidence_ref in validated.evidence_refs
                    ),
                )
            )
            persisted = await self._compact_service.get(compact.id)
            _verify_read_back(compact, persisted)
        return ResumePackageSeal(
            package_id=persisted.id,
            package_revision=package_revision,
            previous_package_id=previous_package_id,
            draft_hash=validated.draft_hash,
            deduplicated=False,
            source_set_hash=persisted.source_set_hash,
            compaction_policy_version=persisted.compaction_policy_version,
            generated_at=persisted.generated_at,
            markdown_body=persisted.markdown_body,
            request_id=validated.draft.request_id,
        )

    async def get_resume_package(self, package_id: str) -> ResumePackageView:
        """Reopen one stored resume package as a structured view.

        Args:
            package_id: Memory Compact identifier of the resume package.

        Returns:
            Structured package view with parsed sections, lineage, revision,
            evidence references, and compact provenance.

        Raises:
            MemoryCompactNotFoundError: When no compact exists for the id.
            MemoryResumePackageValidationError: When the compact is not a
                canonical resume package.
        """
        compact = await self._compact_service.get(package_id)
        parsed = parse_resume_package_markdown(compact.markdown_body)
        return ResumePackageView(
            package_id=compact.id,
            project=compact.project,
            status=compact.status,
            covered_from=compact.covered_from,
            covered_to=compact.covered_to,
            goal=parsed.goal,
            summary=parsed.summary,
            current_state=parsed.current_state,
            next_single_action=parsed.next_single_action,
            accepted_changes=parsed.accepted_changes,
            constraints=parsed.constraints,
            verified_complete=parsed.verified_complete,
            implemented_unverified=parsed.implemented_unverified,
            unfinished_tasks=parsed.unfinished_tasks,
            uncertain_results=parsed.uncertain_results,
            blockers=parsed.blockers,
            evidence_refs=parsed.evidence_refs,
            lineage=ResumePackageLineage(
                lineage_id=parsed.lineage_id,
                worker_id=parsed.worker_id,
                run_id=parsed.run_id,
                workspace_id=parsed.workspace_id,
                session_id=parsed.session_id,
                previous_package_id=parsed.previous_package_id,
                package_revision=parsed.package_revision,
            ),
            draft_hash=parsed.draft_hash,
            source_set_hash=compact.source_set_hash,
            compaction_policy_version=compact.compaction_policy_version,
            compact_generation_revision=compact.generation_revision,
            generated_at=compact.generated_at,
            deduplicated=compact.deduplicated,
            markdown_body=compact.markdown_body,
            request_id=parsed.request_id,
        )

    async def _collect_evidence(
        self,
        evidence_context_ids: tuple[str, ...],
    ) -> _ObservedEvidence:
        """Resolve evidence context ids into observed evidence references.

        Args:
            evidence_context_ids: Caller-supplied stored Context identifiers.

        Returns:
            Observed evidence references and source titles.

        Raises:
            MemoryResumePackageEvidenceNotFoundError: When a referenced
                Context is not stored.
        """
        refs: list[ResumePackageEvidenceRef] = []
        titles: dict[str, str] = {}
        seen: set[str] = set()
        for context_id in evidence_context_ids:
            normalized = context_id.strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            record = await self._observe_context(normalized)
            titles[normalized] = record.title
            refs.append(
                ResumePackageEvidenceRef(
                    context_id=normalized,
                    content_hash=sha256(record.content.encode("utf-8")).hexdigest(),
                    source=f"{record.source_type.value}:{record.source_agent}",
                    created_at=record.created_at,
                    observed_updated_at=record.updated_at,
                )
            )
        return _ObservedEvidence(refs=tuple(refs), titles_by_context_id=titles)

    async def _observe_context(self, context_id: str) -> ContextRecord:
        """Observe one stored Context record through the evidence seam.

        Args:
            context_id: Stored Context identifier.

        Returns:
            Observed Context read model.

        Raises:
            MemoryResumePackageEvidenceNotFoundError: When the referenced
                Context is not stored.
        """
        try:
            return await self._evidence_source.get(context_id)
        except MemoryContextNotFoundError as exc:
            raise MemoryResumePackageEvidenceNotFoundError(
                f"Resume package evidence context not found: {context_id}"
            ) from exc

    async def _lineage_entries(
        self,
        lineage_id: str,
        project: str | None,
    ) -> tuple[ResumePackageLineageEntry, ...]:
        """Scan stored compacts for packages already sealed on one lineage.

        Args:
            lineage_id: Stable lineage identity to match.
            project: Optional project scope for the compact listing.

        Returns:
            Lineage entries in unspecified order.
        """
        entries: list[ResumePackageLineageEntry] = []
        offset = 0
        while True:
            compacts, total = await self._compact_service.list_compacts(
                project=project,
                limit=200,
                offset=offset,
            )
            for compact in compacts:
                entry = _lineage_entry_if_matching(compact, lineage_id)
                if entry is not None:
                    entries.append(entry)
            if not compacts or offset + len(compacts) >= total:
                return tuple(entries)
            offset += len(compacts)

    async def _seal_from_stored(
        self,
        package_id: str,
        *,
        deduplicated: bool,
    ) -> ResumePackageSeal:
        """Build a seal from an already stored package.

        Args:
            package_id: Stored resume package identifier.
            deduplicated: Whether this seal reports duplicate reuse.

        Returns:
            Sealed package identity read back from storage.
        """
        compact = await self._compact_service.get(package_id)
        parsed = parse_resume_package_markdown(compact.markdown_body)
        return ResumePackageSeal(
            package_id=compact.id,
            package_revision=parsed.package_revision,
            previous_package_id=parsed.previous_package_id,
            draft_hash=parsed.draft_hash,
            deduplicated=deduplicated,
            source_set_hash=compact.source_set_hash,
            compaction_policy_version=compact.compaction_policy_version,
            generated_at=compact.generated_at,
            markdown_body=compact.markdown_body,
            request_id=parsed.request_id,
        )


def _lineage_entry_if_matching(
    compact: MemoryCompact,
    lineage_id: str,
) -> ResumePackageLineageEntry | None:
    """Return a lineage entry when the compact is a package of the lineage.

    Args:
        compact: Stored Memory Compact entity under inspection.
        lineage_id: Stable lineage identity to match.

    Returns:
        Lineage entry, or None when the compact is not a canonical package of
        this lineage.
    """
    try:
        parsed = parse_resume_package_markdown(compact.markdown_body)
    except MemoryResumePackageValidationError:
        return None
    if parsed.lineage_id != lineage_id:
        return None
    return ResumePackageLineageEntry(
        package_id=compact.id,
        package_revision=parsed.package_revision,
        draft_hash=parsed.draft_hash,
        updated_at=compact.updated_at,
        request_id=parsed.request_id,
    )


def _reject_request_id_conflict(
    lineage_entries: tuple[ResumePackageLineageEntry, ...],
    validated: ValidatedResumePackage,
) -> None:
    """Reject a sealed request id that is retried with different content.

    Args:
        lineage_entries: Stored packages already observed in the lineage.
        validated: Normalized draft with its sealed content hash.

    Raises:
        MemoryResumePackageRequestConflictError: When a stored package of
            this lineage carries the same request id with a different draft
            hash.
    """
    request_id = validated.draft.request_id
    if request_id is None:
        return
    conflicting = next(
        (
            entry
            for entry in lineage_entries
            if entry.request_id == request_id
            and entry.draft_hash != validated.draft_hash
        ),
        None,
    )
    if conflicting is not None:
        raise MemoryResumePackageRequestConflictError(
            "Resume package request id was already sealed with different "
            f"content: {request_id}"
        )


def _verify_read_back(
    created: MemoryCompact,
    persisted: MemoryCompact,
) -> None:
    """Verify that a created package persisted with its sealed identity.

    Args:
        created: Compact entity returned by the creation path.
        persisted: Compact entity read back from durable storage.

    Raises:
        MemoryResumePackageValidationError: When the read-back identity or
            body differs from the sealed creation result.
    """
    if created.id == persisted.id and (
        created.markdown_body.strip() == persisted.markdown_body.strip()
    ):
        return
    raise MemoryResumePackageValidationError(
        f"Resume package failed durable read-back verification: {created.id}"
    )
