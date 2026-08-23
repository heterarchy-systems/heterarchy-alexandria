"""Obsidian implementation of canonical Context reconciliation mutations."""

from __future__ import annotations

from datetime import datetime

from pydantic import TypeAdapter, ValidationError

from app.memory.application.integration.obsidian_context_read_mapper import (
    OBSIDIAN_CONTEXT_ID_PREFIX,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemorySourceReference,
)
from app.memory.domain.event_enum.context_enums import ContextKind, ContextSourceType
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryRelationType,
)
from app.memory.domain.repositories.contexts.memory_canonical_mutation_gateway import (
    IMemoryCanonicalMutationGateway,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianMutationPort
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianContextLifecycleStatus,
    ObsidianIndexStatus,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.types.types_convert_utils import now_utc

_CLAIMS_ADAPTER = TypeAdapter(tuple[CanonicalClaim, ...])
_SOURCE_REFS_ADAPTER = TypeAdapter(tuple[MemorySourceReference, ...])


class ObsidianMemoryCanonicalMutationGateway(IMemoryCanonicalMutationGateway):
    """Mutate reconciliation Contexts through the canonical Obsidian service."""

    def __init__(self, service: ObsidianMutationPort) -> None:
        """Initialize ObsidianMemoryCanonicalMutationGateway state and dependencies.

        Args:
            service: Application service used by this operation.
        """
        self._service = service

    async def create_context(
        self,
        candidate: MemoryCandidate,
        lifecycle_status: str,
        supersedes_context_id: str | None = None,
        conflict_set_ids: tuple[str, ...] = (),
        relation: MemoryRelationType | None = None,
        related_context_id: str | None = None,
    ) -> str:
        """Create one canonical Context with temporal and claim metadata.

        Args:
            candidate: Candidate.
            lifecycle_status: Lifecycle status.
            supersedes_context_id: Supersedes context id.
            conflict_set_ids: Conflict set ids.
            relation: Relation.
            related_context_id: Related context id.

        Returns:
            str: Operation result.
        """
        status = _lifecycle_status(lifecycle_status)
        related_note = (
            await self._read_context(related_context_id)
            if relation is not None and related_context_id is not None
            else None
        )
        frontmatter = _candidate_frontmatter(
            candidate,
            supersedes_context_id=supersedes_context_id,
            conflict_set_ids=conflict_set_ids,
            relation=relation,
            related_note=related_note,
        )
        try:
            note = await self._service.save_note(
                ObsidianSaveNote(
                    note_id=candidate.candidate_id,
                    title=candidate.title,
                    body=candidate.body,
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    tags=tuple(candidate.tags),
                    status=status,
                    project=candidate.project,
                    source="memory-reconciliation",
                    frontmatter=frontmatter,
                )
            )
        except ObsidianValidationError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        return _qualified_context_id(note.note_id)

    async def merge_evidence(
        self,
        context_id: str,
        evidence: tuple[MemorySourceReference, ...],
    ) -> str:
        """Merge source references into canonical Context frontmatter.

        Args:
            context_id: Context id.
            evidence: Evidence.

        Returns:
            str: Operation result.
        """
        note = await self._read_context(context_id)
        existing_refs = _source_refs(note.frontmatter.get("memory_source_refs"))
        merged_refs = _merge_source_refs(existing_refs, evidence)
        frontmatter = dict(note.frontmatter)
        frontmatter["evidence_refs"] = list(
            dict.fromkeys(
                [
                    *_string_list(note.frontmatter.get("evidence_refs")),
                    *(item.detail_path for item in evidence),
                ]
            )
        )
        frontmatter["memory_source_refs"] = _SOURCE_REFS_ADAPTER.dump_python(
            merged_refs,
            mode="json",
        )
        frontmatter["updated_at"] = now_utc().isoformat()
        version = note.frontmatter.get("version")
        frontmatter["version"] = version + 1 if isinstance(version, int) else 1
        try:
            saved = await self._service.save_note(
                ObsidianSaveNote(
                    note_id=note.note_id,
                    relative_path=note.relative_path,
                    title=note.title,
                    body=note.body,
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    tags=tuple(note.tags),
                    status=note.status,
                    project=note.project,
                    source=note.source or "memory-reconciliation",
                    frontmatter=frontmatter,
                )
            )
        except ObsidianValidationError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        return _qualified_context_id(saved.note_id)

    async def supersede(
        self,
        context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Link two canonical Context notes through the existing lifecycle service.

        Args:
            context_id: Context id.
            replacement_context_id: Replacement context id.
        """
        note_id = _note_id(context_id)
        replacement_note_id = _note_id(replacement_context_id)
        if note_id is None or replacement_note_id is None:
            raise MemoryContextValidationError(
                "Supersede requires source-qualified Obsidian Context identifiers"
            )
        try:
            await self._service.supersede_context(note_id, replacement_note_id)
        except ObsidianNotFoundError as exc:
            raise MemoryContextNotFoundError(
                "Superseded or replacement Context was not found"
            ) from exc
        except ObsidianValidationError as exc:
            raise MemoryContextValidationError(str(exc)) from exc

    async def verify(self, context_id: str) -> bool:
        """Read one Context back from canonical storage and require indexed status.

        Args:
            context_id: Context id.

        Returns:
            bool: Operation result.
        """
        try:
            note = await self._read_context(context_id)
        except MemoryContextNotFoundError:
            return False
        return note.index_status is ObsidianIndexStatus.INDEXED

    async def _read_context(self, context_id: str) -> ObsidianNote:
        """Read context.

        Args:
            context_id: Identifier for context.

        Returns:
            Loaded context.
        """
        note_id = _note_id(context_id)
        if note_id is None:
            raise MemoryContextNotFoundError(f"Context not found: {context_id}")
        try:
            note = await self._service.read_note(note_id)
        except ObsidianNotFoundError as exc:
            raise MemoryContextNotFoundError(
                f"Context not found: {context_id}"
            ) from exc
        if note.alexandria_type is not AlexandriaNoteType.CONTEXT:
            raise MemoryContextValidationError(
                f"Canonical note is not a Context: {context_id}"
            )
        return note


def _candidate_frontmatter(
    candidate: MemoryCandidate,
    supersedes_context_id: str | None,
    conflict_set_ids: tuple[str, ...],
    relation: MemoryRelationType | None,
    related_note: ObsidianNote | None,
) -> JSONObject:
    """Execute candidate frontmatter.

    Args:
        candidate: Candidate used by this operation.
        supersedes_context_id: Identifier for supersedes context.
        conflict_set_ids: Identifiers for conflict set.
        relation: Relation used by this operation.
        related_note: Related note used by this operation.

    Returns:
        JSONObject result produced by candidate frontmatter.
    """
    frontmatter: JSONObject = {
        "scope": candidate.scope.value,
        "visibility": candidate.scope.value,
        "project": candidate.project,
        "workspace_id": candidate.workspace_id,
        "agent_id": candidate.agent_id,
        "user_id": candidate.user_id,
        "session_id": candidate.session_id,
        "source_actor_id": "memory-reconciliation",
        "source_actor_type": ContextSourceType.SYSTEM.value,
        "evidence_refs": [item.detail_path for item in candidate.source_refs],
        "memory_source_refs": _SOURCE_REFS_ADAPTER.dump_python(
            candidate.source_refs,
            mode="json",
        ),
        "canonical_claims": _CLAIMS_ADAPTER.dump_python(
            candidate.canonical_claims,
            mode="json",
        ),
        "context_kind": ContextKind.MEMORY.value,
        "recorded_at": candidate.recorded_at.isoformat(),
        "observed_at": _datetime_text(candidate.observed_at),
        "valid_from": _datetime_text(candidate.valid_from),
        "valid_to": _datetime_text(candidate.valid_to),
        "reconciliation_candidate_id": candidate.candidate_id,
        "conflict_set_ids": list(conflict_set_ids),
        "supersedes_context_id": _note_id(supersedes_context_id),
    }
    relation_field = _relation_frontmatter_field(relation)
    if relation_field is not None and related_note is not None:
        frontmatter[relation_field] = [
            {
                "id": related_note.note_id,
                "path": related_note.relative_path,
                "relation": relation_field,
            }
        ]
    return frontmatter


def _relation_frontmatter_field(
    relation: MemoryRelationType | None,
) -> str | None:
    """Execute relation frontmatter field.

    Args:
        relation: Relation used by this operation.

    Returns:
        str | None result produced by relation frontmatter field.
    """
    if relation is None or relation is MemoryRelationType.UNRELATED:
        return None
    return {
        MemoryRelationType.DUPLICATE: "duplicates",
        MemoryRelationType.SUPPORTS: "supports",
        MemoryRelationType.EXTENDS: "extends",
        MemoryRelationType.CONTRADICTS: "contradicts",
        MemoryRelationType.SUPERSEDES: "supersedes",
        MemoryRelationType.UNKNOWN: "related",
    }[relation]


def _source_refs(value: JSONValue | None) -> tuple[MemorySourceReference, ...]:
    """Execute source refs.

    Args:
        value: Value being processed.

    Returns:
        tuple[MemorySourceReference, ...] result produced by source refs.
    """
    if not isinstance(value, list):
        return ()
    try:
        return _SOURCE_REFS_ADAPTER.validate_python(value)
    except ValidationError:
        return ()


def _merge_source_refs(
    existing: tuple[MemorySourceReference, ...],
    incoming: tuple[MemorySourceReference, ...],
) -> tuple[MemorySourceReference, ...]:
    """Execute merge source refs.

    Args:
        existing: Existing used by this operation.
        incoming: Incoming used by this operation.

    Returns:
        tuple[MemorySourceReference, ...] result produced by merge source refs.
    """
    merged: list[MemorySourceReference] = []
    seen: set[tuple[str, str, str]] = set()
    for item in (*existing, *incoming):
        key = (item.source_type, item.source_id, item.detail_path)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return tuple(merged)


def _string_list(value: JSONValue | None) -> tuple[str, ...]:
    """Execute string list.

    Args:
        value: Value being processed.

    Returns:
        tuple[str, ...] result produced by string list.
    """
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _lifecycle_status(value: str) -> str:
    """Execute lifecycle status.

    Args:
        value: Value being processed.

    Returns:
        str result produced by lifecycle status.
    """
    try:
        return ObsidianContextLifecycleStatus.from_frontmatter_text(value).value
    except ValueError as exc:
        raise MemoryContextValidationError(
            f"Unsupported reconciliation lifecycle status: {value}"
        ) from exc


def _qualified_context_id(note_id: str) -> str:
    """Execute qualified context id.

    Args:
        note_id: Identifier for note.

    Returns:
        str result produced by qualified context id.
    """
    return f"{OBSIDIAN_CONTEXT_ID_PREFIX}{note_id}"


def _note_id(context_id: str | None) -> str | None:
    """Execute note id.

    Args:
        context_id: Identifier for context.

    Returns:
        str | None result produced by note id.
    """
    if context_id is None or not context_id.startswith(OBSIDIAN_CONTEXT_ID_PREFIX):
        return None
    note_id = context_id.removeprefix(OBSIDIAN_CONTEXT_ID_PREFIX).strip()
    return note_id or None


def _datetime_text(value: datetime | None) -> str | None:
    """Execute datetime text.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by datetime text.
    """
    return None if value is None else value.isoformat()
