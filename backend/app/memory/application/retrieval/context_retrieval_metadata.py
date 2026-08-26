"""Derive typed metadata for Context API results and prompt packs."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.entities.context_read_models import (
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextImportance,
    ContextRecallLifecycleStatus,
    ContextSourceType,
    RagStrategy,
)
from app.memory.domain.types.context_payload_types import ContextRetrievalSource
from app.shared.types.extra_types import JSONValue


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextRetrievalMetadata:
    """Explicit retrieval identity, lifecycle, source, and strategy metadata."""

    canonical_context_id: str
    lifecycle_status: ContextRecallLifecycleStatus
    retrieval_source: ContextRetrievalSource
    retrieval_strategy: RagStrategy
    source_actor_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextProvenanceMetadata:
    """Normalized generalized provenance for one Context record."""

    source_actor_id: str | None
    source_actor_type: ContextSourceType | None
    source_run_id: str | None
    external_run_id: str | None
    artifact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    confidence: ContextImportance | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextLifecycleMetadata:
    """Normalized lifecycle, integrity, and supersede metadata."""

    status: ContextRecallLifecycleStatus
    content_hash: str | None
    version: int | None
    supersedes_context_id: str | None
    superseded_by_context_id: str | None


def retrieval_metadata(match: ContextSearchMatch) -> ContextRetrievalMetadata:
    """Return the single canonical metadata derivation for one search match.

    Args:
        match: Retrieved Context match.

    Returns:
        Typed canonical retrieval metadata.
    """
    return ContextRetrievalMetadata(
        canonical_context_id=canonical_context_id(match.context),
        lifecycle_status=lifecycle_status(match.context),
        retrieval_source=retrieval_source(match.context),
        retrieval_strategy=retrieval_strategy(match),
        source_actor_id=source_actor_id(match.context),
    )


def canonical_context_id(context: ContextRecord) -> str:
    """Return a storage-native identifier without retrieval namespacing.

    Args:
        context: Context read model.

    Returns:
        Canonical storage identifier.
    """
    value = context.context_metadata.get("canonical_context_id")
    if isinstance(value, str) and value:
        return value
    obsidian_note_id = context.context_metadata.get("obsidian_note_id")
    if isinstance(obsidian_note_id, str) and obsidian_note_id:
        return obsidian_note_id
    return context.id


def lifecycle_status(context: ContextRecord) -> ContextRecallLifecycleStatus:
    """Return the lifecycle state represented by one Context read model.

    Args:
        context: Context read model.

    Returns:
        Canonical recall lifecycle status.
    """
    value = context.context_metadata.get("lifecycle_status")
    if isinstance(value, str) and value:
        return ContextRecallLifecycleStatus(value.upper())
    if context.is_archived:
        return ContextRecallLifecycleStatus.ARCHIVED
    return ContextRecallLifecycleStatus(context.status.value)


def provenance_metadata(context: ContextRecord) -> ContextProvenanceMetadata:
    """Return typed provenance with legacy Context fallbacks.

    Args:
        context: Context read model whose metadata contains optional provenance.

    Returns:
        Normalized generalized provenance metadata.
    """
    raw = context.context_metadata.get("provenance")
    provenance = raw if isinstance(raw, dict) else {}
    return ContextProvenanceMetadata(
        source_actor_id=_optional_text(provenance.get("source_actor_id"))
        or context.source_agent,
        source_actor_type=_optional_enum(
            provenance.get("source_actor_type"), ContextSourceType
        )
        or context.source_type,
        source_run_id=_optional_text(provenance.get("source_run_id")),
        external_run_id=_optional_text(provenance.get("external_run_id")),
        artifact_refs=_text_tuple(provenance.get("artifact_refs")),
        evidence_refs=_text_tuple(provenance.get("evidence_refs")),
        confidence=_optional_enum(provenance.get("confidence"), ContextImportance),
    )


def lifecycle_metadata(context: ContextRecord) -> ContextLifecycleMetadata:
    """Return typed lifecycle and integrity metadata for one Context.

    Args:
        context: Context read model whose metadata contains lifecycle fields.

    Returns:
        Normalized lifecycle, integrity, and supersede metadata.
    """
    return ContextLifecycleMetadata(
        status=lifecycle_status(context),
        content_hash=_optional_text(context.context_metadata.get("content_hash")),
        version=_positive_int(context.context_metadata.get("version")),
        supersedes_context_id=_optional_text(
            context.context_metadata.get("supersedes_context_id")
        ),
        superseded_by_context_id=_optional_text(
            context.context_metadata.get("superseded_by_context_id")
        ),
    )


def retrieval_source(context: ContextRecord) -> ContextRetrievalSource:
    """Return the index source independently of creator provenance.

    Args:
        context: Context read model.

    Returns:
        Retrieval index source.
    """
    if context.context_metadata.get("source_surface") == "obsidian_vault":
        return "obsidian_vault"
    return "context_vault"


def retrieval_strategy(match: ContextSearchMatch) -> RagStrategy:
    """Return the strategy evidenced by populated source scores.

    Args:
        match: Retrieved Context match.

    Returns:
        Effective retrieval strategy for the match.
    """
    if match.graph_score is not None:
        return RagStrategy.AUTO
    if match.fts_score is not None and match.vector_score is not None:
        return RagStrategy.HYBRID
    if match.vector_score is not None:
        return RagStrategy.VECTOR_ONLY
    return RagStrategy.FTS_ONLY


def source_actor_id(context: ContextRecord) -> str:
    """Return creator provenance without conflating it with retrieval source.

    Args:
        context: Context read model.

    Returns:
        Creator actor identifier.
    """
    provenance = context.context_metadata.get("provenance")
    if isinstance(provenance, dict):
        value = provenance.get("source_actor_id")
        if isinstance(value, str) and value:
            return value
    return context.source_agent


def _optional_text(value: JSONValue) -> str | None:
    """Execute optional text.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by optional text.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _text_tuple(value: JSONValue) -> tuple[str, ...]:
    """Execute text tuple.

    Args:
        value: Value being processed.

    Returns:
        tuple[str, ...] result produced by text tuple.
    """
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        normalized for item in value if (normalized := _optional_text(item)) is not None
    )


def _positive_int(value: JSONValue) -> int | None:
    """Execute positive int.

    Args:
        value: Value being processed.

    Returns:
        int | None result produced by positive int.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _optional_enum[EnumType: ContextSourceType | ContextImportance](
    value: JSONValue, enum_type: type[EnumType]
) -> EnumType | None:
    """Execute optional enum.

    Args:
        value: Value being processed.
        enum_type: Enum type used by this operation.

    Returns:
        EnumType | None result produced by optional enum.
    """
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return enum_type(text.upper())
    except ValueError:
        return None
