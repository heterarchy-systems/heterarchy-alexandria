"""Input-context and local fallback policy for librarian conversations."""

from __future__ import annotations

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianAsk,
    ObsidianSearchQuery,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONObject

SELECTION_CONTEXT_MAX_CHARS = 4_000


def _delegate_status(payload: ObsidianLibrarianAsk) -> str:
    """Execute delegate status.

    Args:
        payload: Validated payload for this operation.

    Returns:
        str result produced by delegate status.
    """
    if not payload.delegate_to_librarian:
        return "local_only"
    if payload.provider_id or payload.profile_id:
        return "requested_local_fallback"
    return "requested_no_provider_local_fallback"


def _librarian_search_queries(
    query: str,
    limit: int,
    project: str | None,
    preferred_types: tuple[AlexandriaNoteType, ...],
    excluded_types: tuple[AlexandriaNoteType, ...],
) -> tuple[ObsidianSearchQuery, ...]:
    """Execute librarian search queries.

    Args:
        query: Query used by this operation.
        limit: Maximum number of items to process or return.
        project: Project used by this operation.
        preferred_types: Preferred types used by this operation.
        excluded_types: Excluded types used by this operation.

    Returns:
        tuple[ObsidianSearchQuery, ...] result produced by librarian search queries.
    """
    if preferred_types:
        return tuple(
            ObsidianSearchQuery(
                query=query,
                limit=limit,
                alexandria_type=note_type,
                project=project,
            )
            for note_type in preferred_types
        )
    return (
        ObsidianSearchQuery(
            query=query,
            limit=limit,
            excluded_alexandria_types=tuple(excluded_types),
            project=project,
        ),
    )


def _selection_excerpt(selection: str | None) -> str | None:
    """Execute selection excerpt.

    Args:
        selection: Selection used by this operation.

    Returns:
        str | None result produced by selection excerpt.
    """
    if selection is None:
        return None
    normalized = selection.strip()
    if not normalized:
        raise ObsidianValidationError("selection_ingestion_failed: selection is blank")
    if len(normalized) <= SELECTION_CONTEXT_MAX_CHARS:
        return normalized
    return f"{normalized[:SELECTION_CONTEXT_MAX_CHARS]}\n…[selection truncated]"


def _librarian_input_context(
    payload: ObsidianLibrarianAsk,
    active_note: ObsidianNote | None,
    selection_excerpt: str | None,
    source_refs: list[JSONObject],
) -> JSONObject:
    """Execute librarian input context.

    Args:
        payload: Validated payload for this operation.
        active_note: Active note used by this operation.
        selection_excerpt: Selection excerpt used by this operation.
        source_refs: Source refs used by this operation.

    Returns:
        JSONObject result produced by librarian input context.
    """
    active_note_status = "not_requested" if payload.active_note_path is None else "read"
    selection_status = "not_requested" if selection_excerpt is None else "ingested"
    warnings: list[str] = []
    if not source_refs:
        warnings.append(
            "source_miss_is_not_no_related_notes_without_inventory_verification"
        )
    status = "ready"
    if not source_refs and active_note is None and selection_excerpt is None:
        status = "insufficient_inventory"
    return {
        "status": status,
        "active_note_path": payload.active_note_path,
        "active_note_status": active_note_status,
        "selection_status": selection_status,
        "selection_excerpt": selection_excerpt,
        "source_ref_count": len(source_refs),
        "warnings": warnings,
    }
