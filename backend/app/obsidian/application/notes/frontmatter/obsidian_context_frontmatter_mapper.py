"""Map validated Context frontmatter to internal identity and canonical output."""

from __future__ import annotations

from app.memory.domain.contracts.context_recall_contracts import (
    validated_scope_identity,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_boundary import (
    validate_context_frontmatter,
)
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_values import (
    frontmatter_context_id,
    legacy_context_kind,
    lifecycle_status_value,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_identity import (
    ObsidianContextIdentity,
    ObsidianContextProvenance,
)
from app.obsidian.application.notes.obsidian_note_templates import sha256_text
from app.shared.types.extra_types import JSONObject


def context_identity_from_frontmatter(
    frontmatter: JSONObject,
    project: str | None,
    status: str,
    generated_content_hash: str,
) -> ObsidianContextIdentity:
    """Return validated Context identity restored from Obsidian frontmatter.

    Args:
        frontmatter: Parsed JSON-compatible frontmatter payload.
        project: Project value already normalized by the note indexer.
        status: Note lifecycle status already normalized by the note indexer.
        generated_content_hash: Canonical SHA-256 digest of normalized note content.

    Returns:
        Validated identity fields for Context recall.

    Raises:
        ValueError: If scope, identity, lifecycle, or integrity data is invalid.
    """
    boundary = validate_context_frontmatter(frontmatter)
    resolved_project = boundary.project if boundary.project is not None else project
    resolved_status = lifecycle_status_value(boundary.status, status)

    scope = boundary.scope
    if scope is None:
        scope = (
            ContextScope.PROJECT
            if resolved_project is not None
            else ContextScope.GLOBAL
        )

    if (
        boundary.content_hash is not None
        and boundary.content_hash != generated_content_hash
    ):
        raise ValueError("INVALID_CONTENT_HASH: Context body hash does not match")

    nested_provenance = boundary.provenance
    identity = ObsidianContextIdentity(
        scope=scope,
        project=resolved_project,
        workspace_id=boundary.workspace_id,
        agent_id=boundary.agent_id,
        user_id=boundary.user_id,
        session_id=boundary.session_id,
        visibility=boundary.visibility or scope,
        status=resolved_status,
        provenance=ObsidianContextProvenance(
            source_actor_id=_provenance_value(
                boundary.source_actor_id,
                None
                if nested_provenance is None
                else nested_provenance.source_actor_id,
            ),
            source_actor_type=_provenance_value(
                boundary.source_actor_type,
                None
                if nested_provenance is None
                else nested_provenance.source_actor_type,
            ),
            source_run_id=_provenance_value(
                boundary.source_run_id,
                None if nested_provenance is None else nested_provenance.source_run_id,
            ),
            external_run_id=_provenance_value(
                boundary.external_run_id,
                None
                if nested_provenance is None
                else nested_provenance.external_run_id,
            ),
            artifact_refs=_provenance_value(
                boundary.artifact_refs,
                None if nested_provenance is None else nested_provenance.artifact_refs,
            ),
            evidence_refs=_provenance_value(
                boundary.evidence_refs,
                None if nested_provenance is None else nested_provenance.evidence_refs,
            ),
            confidence=_provenance_value(
                boundary.confidence,
                None if nested_provenance is None else nested_provenance.confidence,
            ),
        ),
        content_hash=boundary.content_hash or generated_content_hash,
        version=boundary.version or 1,
        supersedes_context_id=boundary.supersedes_context_id,
        superseded_by_context_id=boundary.superseded_by_context_id,
        context_kind=boundary.context_kind or legacy_context_kind(boundary.kind),
        created_at=boundary.created_at,
        updated_at=boundary.updated_at,
        recorded_at=boundary.recorded_at,
        observed_at=boundary.observed_at,
        valid_from=boundary.valid_from,
        valid_to=boundary.valid_to,
        reconciliation_candidate_id=boundary.reconciliation_candidate_id,
        conflict_set_ids=boundary.conflict_set_ids,
    )
    context_id = frontmatter_context_id(frontmatter)
    for related_context_id in (
        identity.supersedes_context_id,
        identity.superseded_by_context_id,
    ):
        if context_id is not None and related_context_id == context_id:
            raise ValueError("INVALID_SUPERSEDE: Context cannot supersede itself")
    validate_scope_identity(identity)
    return identity


def normalized_context_frontmatter(identity: ObsidianContextIdentity) -> JSONObject:
    """Return canonical identity, lifecycle, and provenance frontmatter.

    Args:
        identity: Validated Context identity and metadata.

    Returns:
        Canonical frontmatter fields for Markdown persistence.
    """
    provenance = identity.provenance
    return {
        "scope": identity.scope.value,
        "project": identity.project,
        "workspace_id": identity.workspace_id,
        "agent_id": identity.agent_id,
        "user_id": identity.user_id,
        "session_id": identity.session_id,
        "visibility": identity.visibility.value,
        "status": identity.status.value,
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
        "content_hash": identity.content_hash,
        "version": identity.version,
        "supersedes_context_id": identity.supersedes_context_id,
        "superseded_by_context_id": identity.superseded_by_context_id,
        "context_kind": identity.context_kind.value,
        "created_at": (
            None if identity.created_at is None else identity.created_at.isoformat()
        ),
        "updated_at": (
            None if identity.updated_at is None else identity.updated_at.isoformat()
        ),
        "recorded_at": (
            None if identity.recorded_at is None else identity.recorded_at.isoformat()
        ),
        "observed_at": (
            None if identity.observed_at is None else identity.observed_at.isoformat()
        ),
        "valid_from": (
            None if identity.valid_from is None else identity.valid_from.isoformat()
        ),
        "valid_to": (
            None if identity.valid_to is None else identity.valid_to.isoformat()
        ),
        "reconciliation_candidate_id": identity.reconciliation_candidate_id,
        "conflict_set_ids": list(identity.conflict_set_ids),
    }


def context_content_hash(content: str) -> str:
    """Return the canonical SHA-256 digest for Context Markdown body content.

    Args:
        content: Context Markdown body.

    Returns:
        Lowercase SHA-256 hexadecimal digest of normalized body content.
    """
    return sha256_text(content.strip("\n"))


def validate_scope_identity(identity: ObsidianContextIdentity) -> None:
    """Validate required identity fields for one Context scope.

    Args:
        identity: Context identity restored from frontmatter.
    """
    validated_scope_identity(
        (identity.scope,),
        identity.project,
        identity.workspace_id,
        identity.agent_id,
        identity.user_id,
        identity.session_id,
    )


def _provenance_value[Value](
    flat_value: Value,
    nested_value: Value | None,
) -> Value:
    if flat_value not in (None, ()) or nested_value is None:
        return flat_value
    return nested_value
