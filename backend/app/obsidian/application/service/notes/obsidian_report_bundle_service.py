"""Idempotent Source/owner/reindex/graph report bundle orchestration."""

from __future__ import annotations

from dataclasses import replace

from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.service.notes.obsidian_report_bundle_support import (
    ObsidianReportBundleSupport,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexService,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleRequest,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNoteWriteResult,
    ObsidianReportBundleGraphResult,
    ObsidianReportBundleResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianFrontmatterMode,
    ObsidianIndexStatus,
    ObsidianReportBundleCompletionStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.common_exceptions import IndexMaintenanceConflictError
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianIdempotencyConflictError,
    ObsidianNotFoundError,
    ObsidianValidationError,
)
from app.shared.types.extra_types import JSONObject


class ObsidianReportBundleService:
    """Own one durable, retry-safe report write and graph verification boundary."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        vault_reindex_service: ObsidianVaultReindexService,
        graph_service: ObsidianGraphService,
        vault_config_store: ObsidianVaultConfigStore,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
    ) -> None:
        self._obsidian_service = obsidian_service
        self._vault_reindex_service = vault_reindex_service
        self._graph_service = graph_service
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._support = ObsidianReportBundleSupport(
            obsidian_service=obsidian_service,
            vault_config_store=vault_config_store,
        )

    async def upsert(
        self,
        request: ObsidianReportBundleRequest,
    ) -> ObsidianReportBundleResult:
        """Upsert a report source, update owners, rebuild, and verify graph edges.

        Args:
            request: Value supplied to upsert.

        Returns:
            Result produced by upsert.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_report_bundle",
            wait=True,
        ):
            return await self._upsert_serialized(request)

    async def _upsert_serialized(
        self,
        request: ObsidianReportBundleRequest,
    ) -> ObsidianReportBundleResult:
        key = request.idempotency_key.strip()
        if not key:
            raise ObsidianValidationError("idempotency_key is required")
        normalized = self._support.normalize_request(
            replace(request, idempotency_key=key)
        )
        request_hash = self._support.request_hash(normalized)
        store = ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )
        checkpoint = store.load(key)
        if checkpoint is not None and checkpoint.get("request_hash") != request_hash:
            raise ObsidianIdempotencyConflictError
        replay = await self._support.completed_replay(normalized, checkpoint)
        if replay is not None:
            return replay

        try:
            owners = [
                await self._obsidian_service.read_note_by_path(owner.path)
                for owner in normalized.graph_owners
            ]
        except ObsidianNotFoundError as exc:
            result = self._support.failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.FAILED_NO_MUTATION,
                stage="PREFLIGHT_GRAPH_OWNERS",
                error=exc,
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        try:
            source_result = await self._obsidian_service.write_note(
                ObsidianWriteNote(
                    note=normalized.source,
                    write_mode=ObsidianWriteMode.UPSERT,
                    match_by=ObsidianWriteMatchBy.PATH,
                    frontmatter_mode=ObsidianFrontmatterMode.MERGE,
                )
            )
        except (OSError, ObsidianDomainError) as exc:
            result = self._support.failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.FAILED_NO_MUTATION,
                stage="UPSERT_SOURCE",
                error=exc,
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        owner_writes: list[ObsidianNoteWriteResult] = []
        try:
            for owner_contract, owner_note in zip(
                normalized.graph_owners,
                owners,
                strict=True,
            ):
                owner_writes.append(
                    await self._support.update_owner(
                        owner_contract, owner_note, source_result
                    )
                )
        except (OSError, ObsidianDomainError) as exc:
            status = (
                ObsidianReportBundleCompletionStatus.PARTIAL_OWNER_UPDATE
                if owner_writes
                else ObsidianReportBundleCompletionStatus.PARTIAL_SOURCE_SAVED
            )
            result = self._support.failure(
                request=normalized,
                status=status,
                stage="UPDATE_GRAPH_OWNERS",
                error=exc,
                source=source_result,
                owner_writes=tuple(owner_writes),
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        if not normalized.reindex:
            result = self._support.failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.PARTIAL_INDEXED,
                stage="REINDEX_DISABLED",
                error=ObsidianValidationError(
                    "report bundle verification requires reindex=true"
                ),
                source=source_result,
                owner_writes=tuple(owner_writes),
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        try:
            reindex_report = await self._vault_reindex_service.rebuild()
            source_note = await self._obsidian_service.read_note(
                source_result.note.note_id
            )
        except (
            OSError,
            ObsidianDomainError,
            IndexMaintenanceConflictError,
        ) as exc:
            result = self._support.failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.PARTIAL_INDEXED,
                stage="REINDEX",
                error=exc,
                source=source_result,
                owner_writes=tuple(owner_writes),
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        projection_status = reindex_report.graph_projection.status
        if projection_status == "failed" or (
            projection_status == "disabled" and normalized.verify.incoming_edges
        ):
            projection_error_items: list[JSONObject] = [
                {
                    "function": "graph_projection_rebuild",
                    "message": error.detail or error.code,
                    "code": error.code,
                }
                for error in reindex_report.graph_projection.errors
            ]
            if not projection_error_items:
                projection_error_items.append(
                    {
                        "function": "graph_projection_rebuild",
                        "message": f"graph projection rebuild was {projection_status}",
                    }
                )
            result = ObsidianReportBundleResult(
                completion_status=(
                    ObsidianReportBundleCompletionStatus.PARTIAL_GRAPH_UNVERIFIED
                ),
                idempotency_key=key,
                replayed=False,
                source=replace(source_result, note=source_note),
                owner_writes=tuple(owner_writes),
                graph=ObsidianReportBundleGraphResult(
                    expected_incoming_edges=len(normalized.graph_owners),
                    verified_incoming_edges=0,
                    unresolved_links=tuple(sorted(note.note_id for note in owners)),
                ),
                failed_stage="REBUILD_GRAPH_PROJECTION",
                errors=tuple(projection_error_items),
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        if (
            normalized.verify.index_status
            and source_note.index_status is not ObsidianIndexStatus.INDEXED
        ):
            result = self._support.failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.PARTIAL_INDEXED,
                stage="VERIFY_INDEX_STATUS",
                error=ObsidianValidationError("source note is not indexed"),
                source=replace(source_result, note=source_note),
                owner_writes=tuple(owner_writes),
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        source_result = replace(source_result, note=source_note)
        duplicates = (
            await self._support.duplicate_paths(normalized, source_note)
            if normalized.verify.duplicates
            else ()
        )
        expected_owner_ids = {note.note_id for note in owners}
        verified_owner_ids: set[str] = set()
        graph_errors: list[JSONObject] = []
        if normalized.verify.incoming_edges:
            try:
                related = await self._graph_service.related_notes(
                    source_note.note_id,
                    limit=max(10, len(expected_owner_ids) * 4),
                )
                verified_owner_ids = {
                    item.note.note_id
                    for item in related
                    if item.direction == "incoming"
                    and item.note.note_id in expected_owner_ids
                }
            except ObsidianDomainError as exc:
                graph_errors.append(
                    self._support.operation_error("graph_relation_lookup", exc)
                )

        unresolved = tuple(sorted(expected_owner_ids.difference(verified_owner_ids)))
        graph = ObsidianReportBundleGraphResult(
            expected_incoming_edges=len(expected_owner_ids),
            verified_incoming_edges=len(verified_owner_ids),
            unresolved_links=unresolved,
        )
        if normalized.verify.incoming_edges and len(verified_owner_ids) != len(
            expected_owner_ids
        ):
            if not graph_errors:
                graph_errors.append(
                    {
                        "function": "graph_relation_lookup",
                        "message": "Expected graph owner edges were not found",
                    }
                )
            result = ObsidianReportBundleResult(
                completion_status=(
                    ObsidianReportBundleCompletionStatus.PARTIAL_GRAPH_UNVERIFIED
                ),
                idempotency_key=key,
                replayed=False,
                source=source_result,
                owner_writes=tuple(owner_writes),
                graph=graph,
                duplicates=duplicates,
                failed_stage="VERIFY_INCOMING_EDGES",
                errors=tuple(graph_errors),
            )
            self._support.save_checkpoint(store, normalized, request_hash, result)
            return result

        warnings: list[JSONObject] = []
        if duplicates:
            warnings.append(
                {
                    "function": "duplicate_verification",
                    "message": "Logical or content duplicates were found",
                    "paths": list(duplicates),
                }
            )
        if reindex_report.graph_projection.issue_total:
            warnings.append(
                {
                    "function": "graph_projection_rebuild",
                    "message": (
                        f"{reindex_report.graph_projection.issue_total} graph "
                        "projection issues were reported"
                    ),
                }
            )
        result = ObsidianReportBundleResult(
            completion_status=(
                ObsidianReportBundleCompletionStatus.COMPLETED_WITH_WARNINGS
                if warnings
                else ObsidianReportBundleCompletionStatus.COMPLETED
            ),
            idempotency_key=key,
            replayed=False,
            source=source_result,
            owner_writes=tuple(owner_writes),
            graph=graph,
            duplicates=duplicates,
            errors=tuple(warnings),
        )
        self._support.save_checkpoint(store, normalized, request_hash, result)
        return result


# Broad type justified: canonical frontmatter values are JSON-compatible scalars.
