"""Safe Obsidian vault move planning, application, and reporting."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

from app.obsidian.application.service.vault.obsidian_vault_move_report import (
    ensure_vault_move_report_available,
    vault_move_report_paths,
    write_vault_move_report,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSearchQuery,
    ObsidianVaultMoveApplyRequest,
    ObsidianVaultMovePlanRequest,
    ObsidianVaultMoveRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianReindexResult,
    ObsidianSearchHit,
    ObsidianVaultMoveApplied,
    ObsidianVaultMoveCandidate,
    ObsidianVaultMovePlan,
    ObsidianVaultMoveReport,
    ObsidianVaultMoveSkip,
    ObsidianVaultMoveVerification,
)
from app.obsidian.infrastructure.markdown.paths import NOTE_SUFFIX, resolve_note_path
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)


# protocol-contract: structural-seam
class ObsidianVaultSearchHook(Protocol):
    """Search capability used to verify an applied move batch."""

    async def __call__(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = True,
    ) -> list[ObsidianSearchHit]:
        """Search indexed notes.

        Args:
            query: Query used by this operation.
            refresh: Whether to refresh source state before the operation.

        Returns:
            list[ObsidianSearchHit] result produced by call.
        """


class ObsidianVaultMoveService:
    """Plan and apply non-destructive vault moves with durable reports."""

    def __init__(
        self,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
        search: ObsidianVaultSearchHook,
    ) -> None:
        """Create the move service.

        Args:
            vault_config_store: Runtime vault location provider.
            reindex: Callback that rebuilds the Obsidian index.
            search: Callback that verifies indexed search after moves.
        """
        self._vault_config_store = vault_config_store
        self._reindex = reindex
        self._search = search

    async def plan(
        self,
        request: ObsidianVaultMovePlanRequest,
    ) -> ObsidianVaultMovePlan:
        """Build a dry-run move plan without mutating the vault.

        Args:
            request: Requested safe moves.

        Returns:
            Safety-validated move plan.
        """
        vault_path = self._vault_config_store.current().vault_path
        moves: list[ObsidianVaultMoveCandidate] = []
        skipped: list[ObsidianVaultMoveSkip] = []
        for move in request.moves:
            issue = _move_safety_issue(vault_path=vault_path, move=move)
            if issue is not None:
                skipped.append(issue)
                continue
            moves.append(
                ObsidianVaultMoveCandidate(
                    source_path=move.source_path,
                    destination_path=move.destination_path,
                    reason=move.reason,
                )
            )
        status = "ready" if moves and not skipped else "blocked" if skipped else "empty"
        return ObsidianVaultMovePlan(
            status=status,
            hard_delete_performed=False,
            moves=tuple(moves),
            skipped=tuple(skipped),
            ambiguous=(),
        )

    async def apply(
        self,
        request: ObsidianVaultMoveApplyRequest,
    ) -> ObsidianVaultMoveReport:
        """Safely apply a move plan, reindex, verify, and write reports.

        Args:
            request: Move application request.

        Returns:
            Markdown/JSON report metadata.
        """
        config = self._vault_config_store.current()
        plan = await self.plan(ObsidianVaultMovePlanRequest(moves=request.moves))
        report_paths = vault_move_report_paths(
            vault_path=config.vault_path,
            alexandria_root=config.alexandria_root,
            request=request,
        )
        ensure_vault_move_report_available(report_paths)
        moved: list[ObsidianVaultMoveApplied] = []
        skipped = list(plan.skipped)
        applicable_moves = _applicable_vault_moves(
            vault_path=config.vault_path,
            moves=plan.moves,
            skipped=skipped,
        )
        source_roots: set[Path] = set()
        for move in applicable_moves:
            source = resolve_note_path(config.vault_path, move.source_path)
            destination = resolve_note_path(config.vault_path, move.destination_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_roots.add(source.parent)
            source.replace(destination)
            moved.append(
                ObsidianVaultMoveApplied(
                    source_path=move.source_path,
                    destination_path=move.destination_path,
                    reason=move.reason,
                )
            )
        reindex_status = "skipped"
        verification_hits = 0
        if request.reindex:
            result = await self._reindex()
            reindex_status = "succeeded" if not result.errors else "failed"
            if request.verification_query is not None:
                hits = await self._search(
                    ObsidianSearchQuery(query=request.verification_query, limit=10),
                    refresh=False,
                )
                verification_hits = len(hits)
        verification = ObsidianVaultMoveVerification(
            source_root_loose_notes_remaining=_loose_note_count(source_roots),
            reindex_status=reindex_status,
            verification_hits=verification_hits,
        )
        status = (
            "succeeded" if moved and not skipped else "partial" if moved else "failed"
        )
        report_markdown_path, report_json_path = write_vault_move_report(
            report_paths=report_paths,
            status=status,
            moved=tuple(moved),
            skipped=tuple(skipped),
            verification=verification,
        )
        return ObsidianVaultMoveReport(
            status=status,
            hard_delete_performed=False,
            moved=tuple(moved),
            skipped=tuple(skipped),
            ambiguous=tuple(plan.ambiguous),
            verification=verification,
            report_markdown_path=report_markdown_path,
            report_json_path=report_json_path,
        )

    def empty_report(
        self,
        report_path: str | None,
    ) -> ObsidianVaultMoveReport:
        """Write and return a no-op move report.

        Args:
            report_path: Optional report path stem.

        Returns:
            Persisted no-op report.
        """
        config = self._vault_config_store.current()
        verification = ObsidianVaultMoveVerification(
            source_root_loose_notes_remaining=0,
            reindex_status="skipped",
            verification_hits=0,
        )
        report_paths = vault_move_report_paths(
            vault_path=config.vault_path,
            alexandria_root=config.alexandria_root,
            request=ObsidianVaultMoveApplyRequest(
                moves=(),
                report_path=report_path,
                reindex=False,
                verification_query=None,
            ),
        )
        report_markdown_path, report_json_path = write_vault_move_report(
            report_paths=report_paths,
            status="no_op",
            moved=(),
            skipped=(),
            verification=verification,
        )
        return ObsidianVaultMoveReport(
            status="no_op",
            hard_delete_performed=False,
            moved=(),
            skipped=(),
            ambiguous=(),
            verification=verification,
            report_markdown_path=report_markdown_path,
            report_json_path=report_json_path,
        )


def _move_safety_issue(
    vault_path: Path,
    move: ObsidianVaultMoveRequest,
) -> ObsidianVaultMoveSkip | None:
    """Execute move safety issue.

    Args:
        vault_path: Vault path used by this operation.
        move: Move used by this operation.

    Returns:
        ObsidianVaultMoveSkip | None result produced by move safety issue.
    """
    source = resolve_note_path(vault_path, move.source_path)
    destination = resolve_note_path(vault_path, move.destination_path)
    reason = move.reason.strip()
    if not reason:
        return _move_skip(move, "reason_required")
    if source == destination:
        return _move_skip(move, "source_equals_destination")
    if source.suffix != NOTE_SUFFIX or destination.suffix != NOTE_SUFFIX:
        return _move_skip(move, "only_markdown_notes_can_be_moved")
    if not source.exists():
        return _move_skip(move, "source_missing")
    if not source.is_file():
        return _move_skip(move, "source_not_file")
    if destination.exists():
        return _move_skip(move, "destination_exists")
    return None


def _applicable_vault_moves(
    vault_path: Path,
    moves: Sequence[ObsidianVaultMoveCandidate],
    skipped: list[ObsidianVaultMoveSkip],
) -> list[ObsidianVaultMoveCandidate]:
    """Execute applicable vault moves.

    Args:
        vault_path: Vault path used by this operation.
        moves: Moves used by this operation.
        skipped: Skipped used by this operation.

    Returns:
        list[ObsidianVaultMoveCandidate] result produced by applicable vault moves.
    """
    applicable: list[ObsidianVaultMoveCandidate] = []
    seen_sources: set[str] = set()
    seen_destinations: set[str] = set()
    for move in moves:
        request = ObsidianVaultMoveRequest(
            source_path=move.source_path,
            destination_path=move.destination_path,
            reason=move.reason,
        )
        if move.source_path in seen_sources:
            skipped.append(_move_skip(request, "duplicate_source"))
            continue
        if move.destination_path in seen_destinations:
            skipped.append(_move_skip(request, "duplicate_destination"))
            continue
        issue = _move_safety_issue(vault_path=vault_path, move=request)
        if issue is not None:
            skipped.append(issue)
            continue
        seen_sources.add(move.source_path)
        seen_destinations.add(move.destination_path)
        applicable.append(move)
    return applicable


def _move_skip(
    move: ObsidianVaultMoveRequest,
    reason: str,
) -> ObsidianVaultMoveSkip:
    """Execute move skip.

    Args:
        move: Move used by this operation.
        reason: Reason used by this operation.

    Returns:
        ObsidianVaultMoveSkip result produced by move skip.
    """
    return ObsidianVaultMoveSkip(
        source_path=move.source_path,
        destination_path=move.destination_path,
        reason=reason,
    )


def _loose_note_count(paths: set[Path]) -> int:
    """Execute loose note count.

    Args:
        paths: Paths used by this operation.

    Returns:
        int result produced by loose note count.
    """
    return sum(
        1
        for path in paths
        if path.exists()
        for child in path.iterdir()
        if child.is_file() and child.suffix == NOTE_SUFFIX
    )
