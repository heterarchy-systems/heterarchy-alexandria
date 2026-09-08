"""Map canonical Obsidian Context notes into Memory read models."""

from __future__ import annotations

from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
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
    ObsidianContextProvenance,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianContextLifecycleStatus,
)
from app.shared.types.extra_types import JSONValue
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
    identity = _identity_from_note(note)
    is_archived = (
        identity.status.value == ContextRecallLifecycleStatus.ARCHIVED.value.lower()
    )
    return ContextRecord(
        id=f"{OBSIDIAN_CONTEXT_ID_PREFIX}{note.note_id}",
        kind=identity.context_kind,
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
        memory_function=identity.memory_function,
    )


def _identity_from_note(note: ObsidianNote) -> ObsidianContextIdentity:
    """Return the Context identity used by one Obsidian recall projection.

    Canonical Context notes remain fail-closed against the complete Context
    frontmatter contract. Other managed note types own different lifecycle, scope,
    kind, and content-hash semantics, so recall derives a minimal Context projection
    instead of reinterpreting foreign frontmatter as a Context contract.

    Args:
        note: Note used by this operation.

    Returns:
        Validated canonical Context identity or a derived generalized projection.
    """
    if note.alexandria_type is AlexandriaNoteType.CONTEXT:
        return context_identity_from_frontmatter(
            note.frontmatter,
            project=note.project,
            status=note.status,
            generated_content_hash=context_content_hash(note.body),
        )

    project = _normalized_project(note.project)
    workspace_id = _projection_text(note.frontmatter.get("workspace_id"))
    agent_id = _projection_text(note.frontmatter.get("agent_id"))
    user_id = _projection_text(note.frontmatter.get("user_id"))
    session_id = _projection_text(note.frontmatter.get("session_id"))
    scope = _projection_scope(
        note,
        project=project,
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id,
    )
    visibility = _projection_context_scope(note.frontmatter.get("visibility")) or scope
    return ObsidianContextIdentity(
        scope=scope,
        project=project,
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id,
        visibility=visibility,
        status=ObsidianContextLifecycleStatus.ACTIVE,
        provenance=ObsidianContextProvenance(
            source_actor_id=None,
            source_actor_type=None,
            source_run_id=None,
            external_run_id=None,
            artifact_refs=(),
            evidence_refs=(),
            confidence=None,
        ),
        content_hash=context_content_hash(note.body),
        version=1,
        supersedes_context_id=None,
        superseded_by_context_id=None,
        context_kind=_kind_from_note(note),
        memory_function=None,
        created_at=None,
        updated_at=None,
    )


def _normalized_project(project: str | None) -> str | None:
    """Return a normalized project identity for generalized recall projection.

    Args:
        project: Indexed project value owned by the source note type.

    Returns:
        Trimmed non-empty project identity when present.
    """
    if project is None:
        return None
    normalized = project.strip()
    return normalized or None


def _projection_scope(
    note: ObsidianNote,
    project: str | None,
    agent_id: str | None,
    user_id: str | None,
    session_id: str | None,
) -> ContextScope:
    """Resolve a safe recall scope without applying the Context write contract.

    Args:
        note: Source note owning the foreign scope vocabulary.
        project: Normalized indexed project identity.
        agent_id: Optional normalized agent identity.
        user_id: Optional normalized user identity.
        session_id: Optional normalized session identity.

    Returns:
        A valid Context recall scope preserving compatible source scope semantics.
    """
    requested = _projection_context_scope(note.frontmatter.get("scope"))
    if requested is ContextScope.GLOBAL:
        return requested
    if requested is ContextScope.PROJECT and project is not None:
        return ContextScope.PROJECT
    if requested is ContextScope.AGENT and agent_id is not None:
        return ContextScope.AGENT
    if requested is ContextScope.SESSION and session_id is not None:
        return ContextScope.SESSION
    if requested is ContextScope.USER and user_id is not None:
        return ContextScope.USER
    return ContextScope.PROJECT if project is not None else ContextScope.GLOBAL


def _projection_context_scope(value: JSONValue | None) -> ContextScope | None:
    """Parse one Context-compatible scope while tolerating foreign vocabularies.

    Args:
        value: Source frontmatter scope or visibility value.

    Returns:
        Matching Context scope when recognized; otherwise None.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return ContextScope(normalized)
    except ValueError:
        return None


def _projection_text(value: JSONValue | None) -> str | None:
    """Normalize one optional foreign identity scalar for recall projection.

    Args:
        value: Source frontmatter scalar.

    Returns:
        Trimmed non-empty text when present.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _context_metadata(
    note: ObsidianNote,
    identity: ObsidianContextIdentity,
) -> ContextMetadataPayload:
    """Execute context metadata.

    Args:
        note: Note used by this operation.
        identity: Identity used by this operation.

    Returns:
        ContextMetadataPayload result produced by context metadata.
    """
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
    if identity.memory_function is not None:
        metadata["memory_function"] = identity.memory_function.value
    temporal_values = (
        ("recorded_at", identity.recorded_at),
        ("observed_at", identity.observed_at),
        ("valid_from", identity.valid_from),
        ("valid_to", identity.valid_to),
    )
    for field_name, timestamp in temporal_values:
        if timestamp is not None:
            metadata[field_name] = timestamp.isoformat()
    if note.source is not None:
        metadata["source"] = note.source
    if note.alexandria_type is not AlexandriaNoteType.CONTEXT:
        metadata["source_status"] = note.status
    return metadata


def _provenance_payload(identity: ObsidianContextIdentity) -> dict[str, JSONValue]:
    """Execute provenance payload.

    Args:
        identity: Identity used by this operation.

    Returns:
        dict[str, JSONValue] result produced by provenance payload.
    """
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
    """Execute kind from note.

    Args:
        note: Note used by this operation.

    Returns:
        ContextKind result produced by kind from note.
    """
    frontmatter_kind = _context_kind_from_frontmatter(note.frontmatter)
    if frontmatter_kind is not None:
        return frontmatter_kind
    if note.alexandria_type is AlexandriaNoteType.MEMORY_COMPACT:
        return ContextKind.COMPACT
    if note.alexandria_type in {AlexandriaNoteType.SKILL, AlexandriaNoteType.PROMPT}:
        return ContextKind.USAGE
    if note.alexandria_type in {
        AlexandriaNoteType.JOB_PLAN,
    }:
        return ContextKind.PLAN
    return ContextKind.MEMORY


def _context_kind_from_frontmatter(
    frontmatter: dict[str, JSONValue],
) -> ContextKind | None:
    """Execute context kind from frontmatter.

    Args:
        frontmatter: Frontmatter used by this operation.

    Returns:
        ContextKind | None result produced by context kind from frontmatter.
    """
    value = frontmatter.get("context_kind") or frontmatter.get("kind")
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return ContextKind(normalized)
    except ValueError:
        return None


def _summary_from_note(note: ObsidianNote) -> str:
    """Execute summary from note.

    Args:
        note: Note used by this operation.

    Returns:
        str result produced by summary from note.
    """
    value = note.frontmatter.get("summary")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _excerpt(note.body)


def _excerpt(text: str, limit: int = 240) -> str:
    """Execute excerpt.

    Args:
        text: Text used by this operation.
        limit: Maximum number of items to process or return.

    Returns:
        str result produced by excerpt.
    """
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"
