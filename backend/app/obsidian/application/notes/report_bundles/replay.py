"""Reconstruct completed report-bundle results from durable cached evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.obsidian.application.notes.report_bundles.checkpoints import (
    _checkpoint_dicts,
    _checkpoint_int,
    _checkpoint_string,
    _checkpoint_strings,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNoteWriteResult,
    ObsidianReportBundleGraphResult,
    ObsidianReportBundleResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianReportBundleCompletionStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianNotFoundError
from app.shared.types.extra_types import JSONObject

if TYPE_CHECKING:
    from app.obsidian.application.service.obsidian_service import ObsidianService


class ReportBundleReplay:
    """Read current note state while reusing cached graph and warning evidence."""

    def __init__(self, obsidian_service: ObsidianService) -> None:
        """Create replay support over the canonical Obsidian note facade.

        Args:
            obsidian_service: Existing facade used to read canonical notes.
        """
        self._obsidian_service = obsidian_service

    async def completed_replay(
        self,
        request: ObsidianReportBundleRequest,
        checkpoint: JSONObject | None,
    ) -> ObsidianReportBundleResult | None:
        """Build a completed replay using the existing checkpoint semantics.

        Args:
            request: Normalized request with its canonical idempotency key.
            checkpoint: Previously persisted report-bundle checkpoint.

        Returns:
            Completed replay result when a reusable checkpoint exists; otherwise None.
        """
        if checkpoint is None or checkpoint.get("completion_status") not in {
            ObsidianReportBundleCompletionStatus.COMPLETED.value,
            ObsidianReportBundleCompletionStatus.COMPLETED_WITH_WARNINGS.value,
        }:
            return None
        source_note_id = checkpoint.get("source_note_id")
        if not isinstance(source_note_id, str):
            return None
        try:
            note = await self._obsidian_service.read_note(source_note_id)
        except ObsidianNotFoundError:
            return None
        expected = _checkpoint_int(checkpoint, "expected_incoming_edges")
        verified = _checkpoint_int(checkpoint, "verified_incoming_edges")
        owner_writes: list[ObsidianNoteWriteResult] = []
        for owner_record in _checkpoint_dicts(checkpoint, "owner_writes"):
            note_id = owner_record.get("note_id")
            operation = owner_record.get("operation")
            if not isinstance(note_id, str) or not isinstance(operation, str):
                continue
            try:
                owner_note = await self._obsidian_service.read_note(note_id)
            except ObsidianNotFoundError:
                continue
            owner_writes.append(
                ObsidianNoteWriteResult(
                    operation=ObsidianWriteOperation(operation),
                    write_mode=ObsidianWriteMode.UPDATE,
                    match_by=ObsidianWriteMatchBy.PATH,
                    note=owner_note,
                    storage_status="unchanged",
                    metadata_status="indexed",
                    fts_status="indexed",
                    graph_edge_index_status="indexed",
                    graph_projection_status="ready",
                    reindex_required=False,
                )
            )
        source = ObsidianNoteWriteResult(
            operation=ObsidianWriteOperation.UNCHANGED,
            write_mode=ObsidianWriteMode.UPSERT,
            match_by=ObsidianWriteMatchBy.PATH,
            note=note,
            storage_status="unchanged",
            metadata_status="indexed",
            fts_status="indexed",
            graph_edge_index_status="indexed",
            graph_projection_status="ready",
            reindex_required=False,
        )
        return ObsidianReportBundleResult(
            completion_status=ObsidianReportBundleCompletionStatus(
                str(checkpoint["completion_status"])
            ),
            idempotency_key=request.idempotency_key,
            replayed=True,
            source=source,
            owner_writes=tuple(owner_writes),
            graph=ObsidianReportBundleGraphResult(
                expected_incoming_edges=expected,
                verified_incoming_edges=verified,
                unresolved_links=tuple(
                    _checkpoint_strings(checkpoint, "unresolved_links")
                ),
            ),
            duplicates=tuple(_checkpoint_strings(checkpoint, "duplicates")),
            failed_stage=_checkpoint_string(checkpoint, "failed_stage"),
            errors=tuple(_checkpoint_dicts(checkpoint, "errors")),
        )
