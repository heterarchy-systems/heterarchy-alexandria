"""Librarian review queue and safe move policy service."""

from __future__ import annotations

from app.obsidian.application.service.librarian.obsidian_librarian_review_policy import (
    _duplicate_skill_note_ids,
    _review_queue_item,
)
from app.obsidian.application.service.vault.obsidian_vault_inventory_service import (
    ObsidianVaultInventoryService,
)
from app.obsidian.application.service.vault.obsidian_vault_move_service import (
    ObsidianVaultMoveService,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianReviewApplyRequest,
    ObsidianLibrarianReviewQueueRequest,
    ObsidianVaultInventoryRequest,
    ObsidianVaultMoveApplyRequest,
    ObsidianVaultMovePlanRequest,
    ObsidianVaultMoveRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianLibrarianReviewQueueItem,
    ObsidianVaultMovePlan,
    ObsidianVaultMoveReport,
)
from app.obsidian.domain.event_enum.obsidian_librarian_review_enums import (
    ReviewQueueStatusMarker,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)

__all__ = (
    "ObsidianLibrarianReviewService",
    "ReviewQueueStatusMarker",
)


class ObsidianLibrarianReviewService:
    """Evaluate curation candidates and delegate safe moves."""

    def __init__(
        self,
        vault_config_store: ObsidianVaultConfigStore,
        inventory_service: ObsidianVaultInventoryService,
        move_service: ObsidianVaultMoveService,
    ) -> None:
        """Create the librarian review service.

        Args:
            vault_config_store: Runtime vault location provider.
            inventory_service: Source of managed note inventory.
            move_service: Safe move planner and executor.
        """
        self._vault_config_store = vault_config_store
        self._inventory_service = inventory_service
        self._move_service = move_service

    async def review_queue(
        self,
        request: ObsidianLibrarianReviewQueueRequest,
    ) -> list[ObsidianLibrarianReviewQueueItem]:
        """List managed notes that need librarian curation.

        Args:
            request: Queue scope and project filter.

        Returns:
            Prioritized curation candidates with suggested next actions.
        """
        items = await self._inventory_service.inventory(
            ObsidianVaultInventoryRequest(scope_path=request.scope_path)
        )
        duplicate_skill_note_ids = _duplicate_skill_note_ids(items)
        candidates: list[ObsidianLibrarianReviewQueueItem] = []
        for item in items:
            if request.project is not None and item.project != request.project:
                continue
            candidate = _review_queue_item(
                item,
                root=self._vault_config_store.current().alexandria_root,
                duplicate_skill_note_ids=duplicate_skill_note_ids,
            )
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(
            key=lambda candidate: (
                -candidate.priority,
                candidate.relative_path.casefold(),
            )
        )
        bounded_limit = min(max(int(request.limit), 1), 200)
        return candidates[:bounded_limit]

    async def plan_moves(
        self,
        request: ObsidianLibrarianReviewQueueRequest,
    ) -> ObsidianVaultMovePlan:
        """Build a dry-run move plan from librarian review candidates.

        Args:
            request: Queue scope and project filter.

        Returns:
            Safety-validated move plan for review candidates that have a
            suggested destination.
        """
        moves = await self._librarian_review_move_requests(request)
        if not moves:
            return ObsidianVaultMovePlan(
                status="empty",
                hard_delete_performed=False,
                moves=(),
                skipped=(),
                ambiguous=(),
            )
        return await self._move_service.plan(
            ObsidianVaultMovePlanRequest(moves=tuple(moves))
        )

    async def apply_moves(
        self,
        request: ObsidianLibrarianReviewApplyRequest,
    ) -> ObsidianVaultMoveReport:
        """Apply safe moves generated from librarian review candidates.

        Args:
            request: Queue scope plus report/reindex options.

        Returns:
            Move application report written through the existing safe move path.
        """
        moves = await self._librarian_review_move_requests(
            ObsidianLibrarianReviewQueueRequest(
                scope_path=request.scope_path,
                project=request.project,
                limit=request.limit,
            )
        )
        if not moves:
            return self._move_service.empty_report(report_path=request.report_path)
        return await self._move_service.apply(
            ObsidianVaultMoveApplyRequest(
                moves=tuple(moves),
                report_path=request.report_path,
                reindex=request.reindex,
                verification_query=request.verification_query,
            )
        )

    async def _librarian_review_move_requests(
        self,
        request: ObsidianLibrarianReviewQueueRequest,
    ) -> list[ObsidianVaultMoveRequest]:
        """Execute librarian review move requests.

        Args:
            request: Validated request for this operation.

        Returns:
            list[ObsidianVaultMoveRequest] result produced by librarian review move requests.
        """
        candidates = await self.review_queue(request)
        return [
            ObsidianVaultMoveRequest(
                source_path=candidate.relative_path,
                destination_path=candidate.suggested_destination_path,
                reason=(f"{candidate.recommended_action}: {candidate.reason}"),
            )
            for candidate in candidates
            if candidate.suggested_destination_path is not None
            and not candidate.requires_human_review
        ]
