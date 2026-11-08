"""Idempotent source, owner, reindex, and graph report-bundle orchestration."""

from __future__ import annotations

from dataclasses import replace

from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.notes.relations.obsidian_relation_mutation_service import (
    ObsidianRelationMutationService,
)
from app.obsidian.application.notes.report_bundles.checkpoints import (
    ReportBundleCheckpoints,
)
from app.obsidian.application.notes.report_bundles.obsidian_report_bundle_identity import (
    normalize_report_bundle_request,
    report_bundle_request_hash,
)
from app.obsidian.application.notes.report_bundles.replay import ReportBundleReplay
from app.obsidian.application.notes.report_bundles.report_bundle_enums import (
    ReportBundleMarker,
    ReportBundleStage,
)
from app.obsidian.application.notes.report_bundles.results import (
    failure,
    operation_error,
)
from app.obsidian.application.notes.report_bundles.verification import (
    ReportBundleVerifier,
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
    ObsidianStoredProjectionError,
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
        """Initialize ObsidianReportBundleService state and dependencies.

        Args:
            obsidian_service: Obsidian service dependency.
            vault_reindex_service: Vault reindex service dependency.
            graph_service: Graph service dependency.
            vault_config_store: Vault config store used by this operation.
            index_maintenance_coordinator: Index maintenance coordinator used by this operation.
        """
        self._obsidian_service = obsidian_service
        self._vault_reindex_service = vault_reindex_service
        self._graph_service = graph_service
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._relation_mutation = ObsidianRelationMutationService(obsidian_service)
        self._checkpoints = ReportBundleCheckpoints()
        self._replay = ReportBundleReplay(obsidian_service)
        self._verifier = ReportBundleVerifier(
            obsidian_service=obsidian_service,
            graph_service=graph_service,
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
        """Execute upsert serialized.

        Args:
            request: Validated request for this operation.

        Returns:
            ObsidianReportBundleResult result produced by upsert serialized.
        """
        key = request.idempotency_key.strip()
        if not key:
            raise ObsidianValidationError("idempotency_key is required")
        normalized = normalize_report_bundle_request(
            request=replace(request, idempotency_key=key),
            alexandria_root=self._vault_config_store.current().alexandria_root,
        )
        request_hash = report_bundle_request_hash(normalized)
        store = ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )
        checkpoint = await self._checkpoints.load(
            store=store,
            idempotency_key=key,
        )
        if checkpoint is not None and checkpoint.get("request_hash") != request_hash:
            raise ObsidianIdempotencyConflictError
        replay = await self._replay.completed_replay(normalized, checkpoint)
        if replay is not None:
            return replay

        try:
            owners = [
                await self._obsidian_service.read_note_by_path(owner.path)
                for owner in normalized.graph_owners
            ]
        except ObsidianNotFoundError as exc:
            result = failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.FAILED_NO_MUTATION,
                stage=ReportBundleStage.PREFLIGHT_GRAPH_OWNERS,
                error=exc,
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
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
        except ObsidianStoredProjectionError:
            raise
        except (OSError, ObsidianDomainError) as exc:
            result = failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.FAILED_NO_MUTATION,
                stage=ReportBundleStage.UPSERT_SOURCE,
                error=exc,
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
            return result

        owner_writes: list[ObsidianNoteWriteResult] = []
        try:
            for owner_contract, owner_note in zip(
                normalized.graph_owners,
                owners,
                strict=True,
            ):
                owner_writes.append(
                    await self._relation_mutation.relate(
                        source=owner_note,
                        target=source_result.note,
                        relation=owner_contract.relation,
                        expected_source_hash=owner_note.content_hash,
                        operation_source=ReportBundleMarker.REPORT_BUNDLE.value,
                    )
                )
        except ObsidianStoredProjectionError:
            raise
        except (OSError, ObsidianDomainError) as exc:
            status = (
                ObsidianReportBundleCompletionStatus.PARTIAL_OWNER_UPDATE
                if owner_writes
                else ObsidianReportBundleCompletionStatus.PARTIAL_SOURCE_SAVED
            )
            result = failure(
                request=normalized,
                status=status,
                stage=ReportBundleStage.UPDATE_GRAPH_OWNERS,
                error=exc,
                source=source_result,
                owner_writes=tuple(owner_writes),
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
            return result

        if not normalized.reindex:
            result = failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.PARTIAL_INDEXED,
                stage=ReportBundleStage.REINDEX_DISABLED,
                error=ObsidianValidationError(
                    "report bundle verification requires reindex=true"
                ),
                source=source_result,
                owner_writes=tuple(owner_writes),
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
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
            result = failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.PARTIAL_INDEXED,
                stage=ReportBundleStage.REINDEX,
                error=exc,
                source=source_result,
                owner_writes=tuple(owner_writes),
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
            return result

        projection_status = reindex_report.graph_projection.status
        if projection_status == "failed":
            projection_error_items: list[JSONObject] = [
                operation_error(
                    function=ReportBundleMarker.GRAPH_PROJECTION_REBUILD.value,
                    error=error.detail or error.code,
                    code=error.code,
                )
                for error in reindex_report.graph_projection.errors
            ]
            if not projection_error_items:
                projection_error_items.append(
                    operation_error(
                        function=ReportBundleMarker.GRAPH_PROJECTION_REBUILD.value,
                        error=f"graph projection rebuild was {projection_status}",
                    )
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
                failed_stage=ReportBundleStage.REBUILD_GRAPH_PROJECTION.value,
                errors=tuple(projection_error_items),
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
            return result

        if (
            normalized.verify.index_status
            and source_note.index_status is not ObsidianIndexStatus.INDEXED
        ):
            result = failure(
                request=normalized,
                status=ObsidianReportBundleCompletionStatus.PARTIAL_INDEXED,
                stage=ReportBundleStage.VERIFY_INDEX_STATUS,
                error=ObsidianValidationError("source note is not indexed"),
                source=replace(source_result, note=source_note),
                owner_writes=tuple(owner_writes),
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
            return result

        source_result = replace(source_result, note=source_note)
        duplicates = (
            await self._verifier.duplicate_paths(normalized, source_note)
            if normalized.verify.duplicates
            else ()
        )
        expected_owner_ids = {note.note_id for note in owners}
        verified_owner_ids: set[str] = set()
        graph_errors: list[JSONObject] = []
        if normalized.verify.incoming_edges:
            verified_owner_ids_result, errors = await self._verifier.incoming_edges(
                source_note_id=source_note.note_id,
                expected_owner_ids=expected_owner_ids,
            )
            verified_owner_ids = verified_owner_ids_result
            graph_errors.extend(errors)

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
                    operation_error(
                        function=ReportBundleMarker.GRAPH_RELATION_LOOKUP.value,
                        error="Expected graph owner edges were not found",
                    )
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
                failed_stage=ReportBundleStage.VERIFY_INCOMING_EDGES.value,
                errors=tuple(graph_errors),
            )
            await self._checkpoints.save(
                store=store,
                request=normalized,
                request_hash=request_hash,
                result=result,
            )
            return result

        warnings: list[JSONObject] = []
        if duplicates:
            warnings.append(
                operation_error(
                    function=ReportBundleMarker.DUPLICATE_VERIFICATION.value,
                    error="Logical or content duplicates were found",
                    paths=list(duplicates),
                )
            )
        if reindex_report.graph_projection.issue_total:
            warnings.append(
                operation_error(
                    function=ReportBundleMarker.GRAPH_PROJECTION_REBUILD.value,
                    error=(
                        f"{reindex_report.graph_projection.issue_total} graph "
                        "projection issues were reported"
                    ),
                )
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
        await self._checkpoints.save(
            store=store,
            request=normalized,
            request_hash=request_hash,
            result=result,
        )
        return result
