"""Truthful relation result assembly for mutation and projection outcomes."""

from __future__ import annotations

from collections.abc import Sequence

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_support import (
    ObsidianGraphNoteRebuildReport,
)
from app.obsidian.application.notes.relations.graph_verification import (
    GraphVerificationDTO,
)
from app.obsidian.application.notes.relations.obsidian_relation_mutation_service import (
    relation_present,
)
from app.obsidian.domain.contracts.obsidian_relation_contracts import (
    ObsidianRelateRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteWriteResult,
)
from app.obsidian.domain.entities.obsidian_relation import (
    ObsidianRelateCheckpoint,
    ObsidianRelateIssue,
    ObsidianRelateResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianWriteOperation
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)


def degraded_commit_result(
    *,
    request: ObsidianRelateRequest,
    source: ObsidianNote,
    target: ObsidianNote,
    write_result: ObsidianNoteWriteResult | None,
    relation_issue: ObsidianRelateIssue,
) -> ObsidianRelateResult:
    """Return source-preserved evidence when request SQL commit is unknown.

    Args:
        request: Normalized relation intent.
        source: Canonical source read after the failed commit.
        target: Canonical relation target.
        write_result: Canonical note write outcome, when returned.
        relation_issue: Actionable commit failure evidence.

    Returns:
        Degraded result preserving the existing source-write evidence.
    """
    return ObsidianRelateResult(
        completion_status=ObsidianRelateCompletionStatus.STORED_WITH_PROJECTION_WARNINGS,
        idempotency_key=request.idempotency_key,
        replayed=False,
        source_note_id=source.note_id,
        target_note_id=target.note_id,
        relation=request.relation,
        source_path=source.relative_path,
        target_path=target.relative_path,
        operation=(
            write_result.operation
            if write_result is not None
            else ObsidianWriteOperation.UNCHANGED
        ),
        content_hash=source.content_hash,
        storage_status=(
            write_result.storage_status if write_result is not None else "unchanged"
        ),
        metadata_status="unknown",
        fts_status="unknown",
        graph_edge_index_status="unknown",
        graph_projection_status="unknown",
        source_link_verified=relation_present(source, target, request.relation),
        target_backlink_verified=False,
        related_notes_verified=False,
        warnings=(relation_issue,),
    )


def build_final_relation_result(
    *,
    request: ObsidianRelateRequest,
    checkpoint: ObsidianRelateCheckpoint | None,
    source: ObsidianNote,
    target: ObsidianNote,
    write_result: ObsidianNoteWriteResult | None,
    mutation_resolved_after_error: bool,
    source_link_exists: bool,
    final_commit_failed: bool,
    verification: GraphVerificationDTO,
    rebuild_report: ObsidianGraphNoteRebuildReport | None,
    warnings: Sequence[ObsidianRelateIssue],
) -> ObsidianRelateResult:
    """Assemble the final relation DTO from explicit outcome evidence.

    Args:
        request: Normalized relation intent.
        checkpoint: Existing replay record, if one was loaded.
        source: Latest canonical source readback.
        target: Canonical relation target.
        write_result: Mutation result, if the gateway returned one.
        mutation_resolved_after_error: Whether readback resolved a raised write.
        source_link_exists: Whether canonical source readback contains the relation.
        final_commit_failed: Whether the derived-index commit failed.
        verification: Exact edge and directional readback evidence.
        rebuild_report: Graph rebuild evidence, when the rebuild returned.
        warnings: Ordered issue evidence collected by the apply loop.

    Returns:
        Final relation result preserving source and projection status flags.
    """
    operation = (
        write_result.operation
        if write_result is not None
        else ObsidianWriteOperation.UNCHANGED
    )
    return ObsidianRelateResult(
        completion_status=(
            ObsidianRelateCompletionStatus.STORED_WITH_PROJECTION_WARNINGS
            if warnings
            else (
                ObsidianRelateCompletionStatus.REPLAYED
                if checkpoint is not None and write_result is None
                else ObsidianRelateCompletionStatus.COMPLETED
            )
        ),
        idempotency_key=request.idempotency_key,
        replayed=checkpoint is not None and write_result is None,
        source_note_id=source.note_id,
        target_note_id=target.note_id,
        relation=request.relation,
        source_path=source.relative_path,
        target_path=target.relative_path,
        operation=operation,
        content_hash=source.content_hash,
        storage_status=(
            "resolved_after_error"
            if mutation_resolved_after_error
            else (write_result.storage_status if write_result else "unchanged")
        ),
        metadata_status=(
            "unknown"
            if final_commit_failed
            else (
                write_result.metadata_status
                if write_result is not None
                else source.index_status.value
            )
        ),
        fts_status=(
            "unknown"
            if final_commit_failed
            else (
                write_result.fts_status
                if write_result is not None
                else source.index_status.value
            )
        ),
        graph_edge_index_status=(
            "unknown"
            if final_commit_failed
            else (
                write_result.graph_edge_index_status
                if write_result is not None
                else ("indexed" if verification.edge_id is not None else "unknown")
            )
        ),
        graph_projection_status=(
            "unknown" if final_commit_failed else verification.projection_status
        ),
        source_link_verified=source_link_exists,
        target_backlink_verified=(
            False if final_commit_failed else verification.target_related
        ),
        related_notes_verified=(
            False if final_commit_failed else verification.source_related
        ),
        graph_edge_id=None if final_commit_failed else verification.edge_id,
        projection_run_id=(
            None
            if final_commit_failed
            else (
                verification.projection_run_id
                if verification.projection_run_id is not None
                else (
                    None if rebuild_report is None else rebuild_report.projection.run_id
                )
            )
        ),
        warnings=tuple(warnings),
    )
