"""Source snapshot and preservation operations for operational recovery."""

from __future__ import annotations

from pathlib import Path

from typing_extensions import TypedDict

from app.obsidian.infrastructure.markdown.paths import discover_managed_markdown_paths
from app.operations.application.recovery.planning.recovery_plan_source_policy import (
    markdown_manifest,
)
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlan,
    RecoverySourceSnapshot,
)


class SourceSnapshotSummaryDict(TypedDict, closed=True):
    """Serialized summary metrics for the admitted source markdown snapshot."""

    managed_markdown_count: int
    representative_path: str | None
    representative_sha256: str | None
    markdown_manifest_count: int


class SourcePreservationResultDict(TypedDict, closed=True):
    """Serialized diff report comparing current vault files against a snapshot."""

    preserved: bool
    managed_markdown_count: int
    removed_count: int
    changed_count: int
    added_count: int
    removed_paths: list[str]
    changed_paths: list[str]
    added_paths: list[str]


async def snapshot_sources(plan: RecoveryPlan) -> SourceSnapshotSummaryDict:
    """Capture summary metrics for the admitted source markdown snapshot.

    Args:
        plan: Admitted recovery plan containing the source snapshot.

    Returns:
        Typed summary of the source markdown inventory.
    """
    return SourceSnapshotSummaryDict(
        managed_markdown_count=plan.source_snapshot.managed_markdown_count,
        representative_path=plan.source_snapshot.representative_path,
        representative_sha256=plan.source_snapshot.representative_sha256,
        markdown_manifest_count=len(plan.source_snapshot.markdown_manifest),
    )


def source_preservation_result(
    snapshot: RecoverySourceSnapshot,
) -> SourcePreservationResultDict:
    """Compare current vault markdown files against the admitted source snapshot.

    Args:
        snapshot: Admitted recovery source snapshot captured before execution.

    Returns:
        Typed diff report indicating whether all managed files were preserved.
    """
    current_manifest = _current_markdown_manifest(snapshot)
    before_paths = set(snapshot.markdown_manifest)
    after_paths = set(current_manifest)
    removed_paths = sorted(before_paths - after_paths)
    added_paths = sorted(after_paths - before_paths)
    changed_paths = sorted(
        path
        for path in before_paths & after_paths
        if snapshot.markdown_manifest[path] != current_manifest[path]
    )
    return SourcePreservationResultDict(
        preserved=not removed_paths and not added_paths and not changed_paths,
        managed_markdown_count=len(snapshot.markdown_manifest),
        removed_count=len(removed_paths),
        changed_count=len(changed_paths),
        added_count=len(added_paths),
        removed_paths=removed_paths,
        changed_paths=changed_paths,
        added_paths=added_paths,
    )


def _current_markdown_manifest(snapshot: RecoverySourceSnapshot) -> dict[str, str]:
    """Build the current markdown inventory manifest for the snapshot's vault root.

    Args:
        snapshot: Recovery source snapshot specifying vault and managed root paths.

    Returns:
        Mapping from vault-relative markdown path to stat inventory token.
    """
    vault = Path(snapshot.vault_path)
    root = vault / snapshot.alexandria_root
    try:
        markdown_files = discover_managed_markdown_paths(root) if root.exists() else []
    except OSError:
        markdown_files = []
    return markdown_manifest(vault, markdown_files)
