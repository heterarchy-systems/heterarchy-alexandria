"""Classification, curation, and canonical path policy for librarian review."""

from __future__ import annotations

from pathlib import Path

from app.obsidian.application.notes.obsidian_note_templates import (
    LIBRARIAN_OPERATIONS_FOLDER,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianLibrarianReviewQueueItem,
    ObsidianVaultInventoryItem,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
)
from app.obsidian.domain.event_enum.obsidian_librarian_review_enums import (
    ReviewQueueStatusMarker,
)

REVIEW_QUEUE_EXCLUDED_STATUSES = frozenset({"archived"})

REVIEW_QUEUE_STATUS_MARKERS = frozenset(
    marker.value for marker in ReviewQueueStatusMarker
)

SKILL_CURATION_STATUSES = frozenset({"deprecated", "stale", "superseded"})


def _review_queue_item(
    item: ObsidianVaultInventoryItem,
    root: str,
    duplicate_skill_note_ids: set[str],
) -> ObsidianLibrarianReviewQueueItem | None:
    """Execute review queue item.

    Args:
        item: Item being processed.
        root: Root used by this operation.
        duplicate_skill_note_ids: Identifiers for duplicate skill note.

    Returns:
        ObsidianLibrarianReviewQueueItem | None result produced by review queue item.
    """
    if item.status.casefold() in REVIEW_QUEUE_EXCLUDED_STATUSES:
        return None
    inside_root = _inside_alexandria_root(item.relative_path, root)
    if inside_root.startswith(f"{LIBRARIAN_OPERATIONS_FOLDER}/"):
        return None
    skill_curation_item = _skill_curation_queue_item(
        item,
        root=root,
        duplicate_skill_note_ids=duplicate_skill_note_ids,
    )
    if skill_curation_item is not None:
        return skill_curation_item
    status_needs_review = item.status.casefold() in REVIEW_QUEUE_STATUS_MARKERS
    if inside_root.startswith("_Inbox/"):
        return _queue_item(
            item,
            reason="inbox_capture",
            recommended_action="classify_and_promote",
            suggested_destination_path=_suggested_canonical_path(item, root=root),
            priority=100,
            confidence=0.85,
            requires_human_review=False,
        )
    if status_needs_review:
        return _queue_item(
            item,
            reason="status_requires_review",
            recommended_action="review_lifecycle_and_destination",
            suggested_destination_path=_suggested_canonical_path(item, root=root),
            priority=90,
            confidence=0.65,
            requires_human_review=True,
        )
    if inside_root.startswith("Skills/Drafts/"):
        return _queue_item(
            item,
            reason="skill_draft",
            recommended_action="promote_to_active_or_mark_deprecated",
            suggested_destination_path=_rooted_path(
                root, f"Skills/Active/{Path(item.relative_path).name}"
            ),
            priority=80,
            confidence=0.70,
            requires_human_review=True,
        )
    if inside_root.startswith("Contexts/Project Context/"):
        return _queue_item(
            item,
            reason="legacy_context_shelf",
            recommended_action="merge_or_move_to_project_contexts",
            suggested_destination_path=_rooted_path(
                root, f"Contexts/Projects/{Path(item.relative_path).name}"
            ),
            priority=60,
            confidence=0.95,
            requires_human_review=False,
        )
    if "/" not in inside_root and inside_root != "START_HERE.md":
        return _queue_item(
            item,
            reason="loose_root_note",
            recommended_action="move_to_canonical_shelf",
            suggested_destination_path=_suggested_canonical_path(item, root=root),
            priority=50,
            confidence=0.75,
            requires_human_review=False,
        )
    return None


def _duplicate_skill_note_ids(
    items: list[ObsidianVaultInventoryItem],
) -> set[str]:
    """Execute duplicate skill note ids.

    Args:
        items: Items being processed.

    Returns:
        set[str] result produced by duplicate skill note ids.
    """
    grouped: dict[tuple[str, str | None], list[ObsidianVaultInventoryItem]] = {}
    for item in items:
        if item.alexandria_type is not AlexandriaNoteType.SKILL:
            continue
        status = item.status.casefold()
        if (
            status in REVIEW_QUEUE_EXCLUDED_STATUSES
            or status in SKILL_CURATION_STATUSES
        ):
            continue
        key = (_normalized_skill_title(item.title), item.project)
        grouped.setdefault(key, []).append(item)
    duplicate_ids: set[str] = set()
    for group in grouped.values():
        if len(group) > 1:
            duplicate_ids.update(item.note_id for item in group)
    return duplicate_ids


def _normalized_skill_title(title: str) -> str:
    """Execute normalized skill title.

    Args:
        title: Title used by this operation.

    Returns:
        str result produced by normalized skill title.
    """
    return " ".join(title.casefold().split())


def _skill_curation_queue_item(
    item: ObsidianVaultInventoryItem,
    root: str,
    duplicate_skill_note_ids: set[str],
) -> ObsidianLibrarianReviewQueueItem | None:
    """Execute skill curation queue item.

    Args:
        item: Item being processed.
        root: Root used by this operation.
        duplicate_skill_note_ids: Identifiers for duplicate skill note.

    Returns:
        ObsidianLibrarianReviewQueueItem | None result produced by skill curation queue item.
    """
    if item.alexandria_type is not AlexandriaNoteType.SKILL:
        return None
    status = item.status.casefold()
    if status == "stale":
        return _queue_item(
            item,
            reason="skill_stale_candidate",
            recommended_action="review_or_refresh_skill_evidence",
            suggested_destination_path=None,
            priority=95,
            confidence=0.80,
            requires_human_review=True,
        )
    if status == "superseded":
        return _queue_item(
            item,
            reason="skill_superseded_candidate",
            recommended_action="review_supersedes_relation_and_deprecation_plan",
            suggested_destination_path=_skill_deprecated_path(item, root=root),
            priority=94,
            confidence=0.80,
            requires_human_review=True,
        )
    if item.note_id in duplicate_skill_note_ids:
        return _queue_item(
            item,
            reason="skill_duplicate_candidate",
            recommended_action="review_duplicate_or_supersedes_relation",
            suggested_destination_path=None,
            priority=92,
            confidence=0.75,
            requires_human_review=True,
        )
    if status == "deprecated":
        return _queue_item(
            item,
            reason="skill_deprecated_candidate",
            recommended_action="review_deprecated_skill_retention_plan",
            suggested_destination_path=_skill_deprecated_path(item, root=root),
            priority=88,
            confidence=0.75,
            requires_human_review=True,
        )
    return None


def _skill_deprecated_path(
    item: ObsidianVaultInventoryItem,
    root: str,
) -> str | None:
    """Execute skill deprecated path.

    Args:
        item: Item being processed.
        root: Root used by this operation.

    Returns:
        str | None result produced by skill deprecated path.
    """
    destination = _rooted_path(
        root, f"Skills/Deprecated/{Path(item.relative_path).name}"
    )
    if destination == item.relative_path:
        return None
    return destination


def _queue_item(
    item: ObsidianVaultInventoryItem,
    reason: str,
    recommended_action: str,
    suggested_destination_path: str | None,
    priority: int,
    confidence: float,
    requires_human_review: bool,
) -> ObsidianLibrarianReviewQueueItem:
    """Execute queue item.

    Args:
        item: Item being processed.
        reason: Reason used by this operation.
        recommended_action: Recommended action used by this operation.
        suggested_destination_path: Suggested destination path used by this operation.
        priority: Priority used by this operation.
        confidence: Confidence used by this operation.
        requires_human_review: Requires human review used by this operation.

    Returns:
        ObsidianLibrarianReviewQueueItem result produced by queue item.
    """
    return ObsidianLibrarianReviewQueueItem(
        note_id=item.note_id,
        relative_path=item.relative_path,
        alexandria_type=item.alexandria_type,
        title=item.title,
        status=item.status,
        tags=item.tags,
        project=item.project,
        reason=reason,
        recommended_action=recommended_action,
        suggested_destination_path=suggested_destination_path,
        priority=priority,
        confidence=confidence,
        requires_human_review=requires_human_review,
        verification_query=item.title,
    )


def _inside_alexandria_root(relative_path: str, root: str) -> str:
    """Execute inside alexandria root.

    Args:
        relative_path: Relative path used by this operation.
        root: Root used by this operation.

    Returns:
        str result produced by inside alexandria root.
    """
    normalized_root = root.strip("/")
    if normalized_root in {"", "."}:
        return relative_path
    prefix = f"{normalized_root}/"
    return relative_path.removeprefix(prefix)


def _rooted_path(root: str, relative_inside_root: str) -> str:
    """Execute rooted path.

    Args:
        root: Root used by this operation.
        relative_inside_root: Relative inside root used by this operation.

    Returns:
        str result produced by rooted path.
    """
    normalized_root = root.strip("/")
    if normalized_root in {"", "."}:
        return relative_inside_root
    return f"{normalized_root}/{relative_inside_root}"


def _suggested_canonical_path(
    item: ObsidianVaultInventoryItem,
    root: str,
) -> str | None:
    """Execute suggested canonical path.

    Args:
        item: Item being processed.
        root: Root used by this operation.

    Returns:
        str | None result produced by suggested canonical path.
    """
    filename = Path(item.relative_path).name
    folder = {
        AlexandriaNoteType.CONTEXT: "Contexts/Projects",
        AlexandriaNoteType.MEMORY_COMPACT: "Memory Compacts",
        AlexandriaNoteType.SKILL: "Skills/Drafts",
        AlexandriaNoteType.PROMPT: "Prompts/Task Prompts",
        AlexandriaNoteType.LIBRARIAN_BRIEF: f"{LIBRARIAN_OPERATIONS_FOLDER}/Briefs",
        AlexandriaNoteType.LIBRARIAN_CHAT: f"{LIBRARIAN_OPERATIONS_FOLDER}/Chats",
        AlexandriaNoteType.JOB_PLAN: "Jobs",
        AlexandriaNoteType.IMPLEMENTATION_HISTORY: "Implementation History",
    }[item.alexandria_type]
    destination = _rooted_path(root, f"{folder}/{filename}")
    if destination == item.relative_path:
        return None
    return destination
