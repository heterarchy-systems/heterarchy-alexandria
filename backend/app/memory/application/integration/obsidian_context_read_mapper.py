"""Map canonical Obsidian Context notes into Memory read models."""

from __future__ import annotations

from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextSourceType,
    ContextStorageStatus,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_identity import (
    ObsidianContextIdentity,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime

OBSIDIAN_CONTEXT_ID_PREFIX = "obsidian:"
OBSIDIAN_SOURCE_AGENT = "obsidian-vault"


def context_record_from_obsidian_note(note: ObsidianNote) -> ContextRecord:
    """Restore one Context read model from a canonical indexed note.

    Args:
        note: Validated indexed Obsidian note.

    Returns:
        Memory Context read model with canonical identity metadata.
    """
    identity = context_identity_from_frontmatter(
        _identity_frontmatter(note),
        project=note.project,
        status=note.status,
        generated_content_hash=context_content_hash(note.body),
    )
    is_archived = (
        identity.status.value == ContextRecallLifecycleStatus.ARCHIVED.value.lower()
    )
    return ContextRecord(
        id=f"{OBSIDIAN_CONTEXT_ID_PREFIX}{note.note_id}",
        kind=(
            identity.context_kind
            if note.alexandria_type is AlexandriaNoteType.CONTEXT
            else _kind_from_note(note)
        ),
        title=note.title,
        summary=_summary_from_note(note),
        content=note.body,
        content_format=ContextContentFormat.MARKDOWN,
        project=identity.project,
        scope=identity.scope,
        workspace_id=identity.workspace_id,
        agent_id=identity.agent_id,
        user_id=identity.user_id,
        session_id=identity.session_id,
        visibility=identity.visibility,
        source_agent=note.source or OBSIDIAN_SOURCE_AGENT,
        source_type=ContextSourceType.IMPORTED,
        importance=ContextImportance.MEDIUM,
        tags=tuple(note.tags),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=f"Open [[{note.relative_path.removesuffix('.md')}]]",
        context_metadata=_context_metadata(note, identity),
        created_at=(
            aware_utc_datetime(note.modified_at)
            if identity.created_at is None
            else aware_utc_datetime(identity.created_at)
        ),
        updated_at=(
            aware_utc_datetime(note.indexed_at)
            if identity.updated_at is None
            else aware_utc_datetime(identity.updated_at)
        ),
        last_accessed_at=None,
        expires_at=None,
        archived_at=aware_utc_datetime(note.indexed_at) if is_archived else None,
        access_count=0,
        is_archived=is_archived,
    )


def _identity_frontmatter(note: ObsidianNote) -> JSONObject:
    """Return frontmatter safe for the shared Memory identity boundary.

    Canonical Context notes own ``ContextKind`` and remain strictly validated.
    Other managed note types may carry their own legacy kind vocabulary, which is
    mapped separately by :func:`_kind_from_note` and must not invalidate recall.
    """
    if note.alexandria_type is AlexandriaNoteType.CONTEXT:
        return note.frontmatter
    frontmatter = dict(note.frontmatter)
    frontmatter.pop("context_kind", None)
    return frontmatter


def _context_metadata(
    note: ObsidianNote,
    identity: ObsidianContextIdentity,
) -> ContextMetadataPayload:
    metadata = ContextMetadataPayload(
        source_surface="obsidian_vault",
        obsidian_note_id=note.note_id,
        canonical_context_id=note.note_id,
        relative_path=note.relative_path,
        alexandria_type=note.alexandria_type.value,
        index_status=note.index_status.value,
        wikilink=f"[[{note.relative_path.removesuffix('.md')}]]",
        lifecycle_status=identity.status.value,
        content_hash=identity.content_hash,
        version=identity.version,
        provenance=_provenance_payload(identity),
        supersedes_context_id=identity.supersedes_context_id,
        superseded_by_context_id=identity.superseded_by_context_id,
    )
    if note.source is not None:
        metadata["source"] = note.source
    return metadata


def _provenance_payload(identity: ObsidianContextIdentity) -> dict[str, JSONValue]:
    provenance = identity.provenance
    return {
        "source_actor_id": provenance.source_actor_id,
        "source_actor_type": (
            None
            if provenance.source_actor_type is None
            else provenance.source_actor_type.value
        ),
        "source_run_id": provenance.source_run_id,
        "external_run_id": provenance.external_run_id,
        "artifact_refs": list(provenance.artifact_refs),
        "evidence_refs": list(provenance.evidence_refs),
        "confidence": (
            None if provenance.confidence is None else provenance.confidence.value
        ),
    }


def _kind_from_note(note: ObsidianNote) -> ContextKind:
    frontmatter_kind = _context_kind_from_frontmatter(note.frontmatter)
    if frontmatter_kind is not None:
        return frontmatter_kind
    if note.alexandria_type is AlexandriaNoteType.MEMORY_COMPACT:
        return ContextKind.COMPACT
    if note.alexandria_type in {AlexandriaNoteType.SKILL, AlexandriaNoteType.PROMPT}:
        return ContextKind.USAGE
    if note.alexandria_type in {
        AlexandriaNoteType.JOB_PLAN,
        AlexandriaNoteType.LIBRARIAN_BRIEF,
    }:
        return ContextKind.PLAN
    return ContextKind.MEMORY


def _context_kind_from_frontmatter(
    frontmatter: dict[str, JSONValue],
) -> ContextKind | None:
    value = frontmatter.get("context_kind") or frontmatter.get("kind")
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return ContextKind(normalized)
    except ValueError:
        return None


def _summary_from_note(note: ObsidianNote) -> str:
    value = note.frontmatter.get("summary")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _excerpt(note.body)


def _excerpt(text: str, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"
