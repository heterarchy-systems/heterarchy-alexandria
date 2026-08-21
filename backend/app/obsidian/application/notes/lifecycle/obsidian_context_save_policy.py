"""Context-specific validation policy for canonical Obsidian saves."""

from __future__ import annotations

from dataclasses import dataclass

from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
    normalized_context_frontmatter,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_identity import (
    ObsidianContextIdentity,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianContextDuplicateQuery,
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextSavePolicyResult:
    """Validated Context frontmatter plus any idempotent existing result."""

    frontmatter: JSONObject
    supersedes_context_id: str | None
    duplicate: ObsidianNote | None


async def apply_context_save_policy(
    payload: ObsidianSaveNote,
    note_id: str,
    frontmatter: JSONObject,
    body: str,
    repository: IObsidianIndexQueryRepository,
) -> ContextSavePolicyResult:
    """Validate Context identity, relations, and duplicate content.

    Args:
        payload: Original typed save request.
        note_id: Resolved canonical note identifier.
        frontmatter: Redacted generated frontmatter.
        body: Canonical Markdown body.
        repository: Rebuildable note index used for relation lookups.

    Returns:
        Normalized frontmatter, supersede target, and optional duplicate result.
    """
    explicit_scope = frontmatter.get("scope")
    if not isinstance(explicit_scope, str) or not explicit_scope.strip():
        raise ObsidianValidationError(
            "INVALID_SCOPE: new Context saves require an explicit scope"
        )
    candidate_frontmatter = dict(frontmatter)
    candidate_frontmatter.pop("content_hash", None)
    try:
        identity = context_identity_from_frontmatter(
            candidate_frontmatter,
            project=payload.project,
            status=payload.status,
            generated_content_hash=context_content_hash(body),
        )
    except ValueError as exc:
        raise ObsidianValidationError(str(exc)) from exc
    candidate_frontmatter.update(normalized_context_frontmatter(identity))
    candidate_frontmatter.pop("provenance", None)
    await _validate_supersede_relations(identity, note_id, repository)
    duplicate = await repository.find_context_duplicate(
        ObsidianContextDuplicateQuery(
            excluded_note_id=note_id,
            scope=identity.scope.value,
            project=identity.project,
            workspace_id=identity.workspace_id,
            agent_id=identity.agent_id,
            user_id=identity.user_id,
            session_id=identity.session_id,
            content_hash=identity.content_hash,
        )
    )
    return ContextSavePolicyResult(
        frontmatter=candidate_frontmatter,
        supersedes_context_id=identity.supersedes_context_id,
        duplicate=duplicate,
    )


async def _validate_supersede_relations(
    identity: ObsidianContextIdentity,
    note_id: str,
    repository: IObsidianIndexQueryRepository,
) -> None:
    supersedes_context_id = identity.supersedes_context_id
    if supersedes_context_id is not None:
        superseded_context = await repository.get_by_id(supersedes_context_id)
        if (
            superseded_context is None
            or superseded_context.alexandria_type is not AlexandriaNoteType.CONTEXT
        ):
            raise ObsidianValidationError(
                "INVALID_SUPERSEDE: superseded Context does not exist"
            )
        existing_replacement = superseded_context.frontmatter.get(
            "superseded_by_context_id"
        )
        if existing_replacement not in (None, note_id):
            raise ObsidianValidationError(
                "INVALID_SUPERSEDE: Context already has a different replacement"
            )
    superseded_by_context_id = identity.superseded_by_context_id
    if superseded_by_context_id is None:
        return
    replacement_context = await repository.get_by_id(superseded_by_context_id)
    replacement_target = (
        None
        if replacement_context is None
        else replacement_context.frontmatter.get("supersedes_context_id")
    )
    if (
        replacement_context is None
        or replacement_context.alexandria_type is not AlexandriaNoteType.CONTEXT
        or replacement_target != note_id
    ):
        raise ObsidianValidationError(
            "INVALID_SUPERSEDE: replacement Context is absent or does not "
            "reference this Context"
        )
