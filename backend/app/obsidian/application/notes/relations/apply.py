"""Apply one durable relation operation under the shared index lease."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.notes.relations.checkpoints import (
    load_checkpoint,
    save_checkpoint,
)
from app.obsidian.application.notes.relations.contracts import (
    issue,
    validate_source_hash,
)
from app.obsidian.application.notes.relations.graph_verification import (
    GraphVerifier,
)
from app.obsidian.application.notes.relations.mapping import (
    build_final_relation_result,
    degraded_commit_result,
)
from app.obsidian.application.notes.relations.obsidian_relation_mutation_service import (
    ObsidianRelationMutationService,
    relation_present,
)
from app.obsidian.application.notes.relations.relation_enums import (
    RelationIssueCapability,
    RelationIssueCode,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
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
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianIdempotencyConflictError,
    ObsidianNotFoundError,
    ObsidianWriteConflictError,
)
from app.shared.exceptions.obsidian_relation_exceptions import (
    ObsidianRelateTargetNotFoundError,
)


class RelationApplyCoordinator:
    """Own the serialized canonical and graph relation application loop."""

    def __init__(
        self,
        *,
        obsidian_service: ObsidianService,
        graph_note_diagnostics_service: ObsidianGraphNoteDiagnosticsService,
        graph_service: ObsidianGraphService,
        graph_repository: IObsidianGraphProjectionRepository,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        commit_projection: Callable[[], Awaitable[None]],
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Create one relation loop over existing note, graph and index owners.

        Args:
            obsidian_service: Canonical note read and mutation boundary.
            graph_note_diagnostics_service: Existing graph rebuild owner.
            graph_service: Existing directed relation read owner.
            graph_repository: Existing active projection read authority.
            index_maintenance_coordinator: Shared operation serialization owner.
            commit_projection: Existing SQLAlchemy projection commit callback.
            rollback_projection: Existing SQLAlchemy projection rollback callback.
        """
        self._obsidian_service = obsidian_service
        self._graph_note_diagnostics_service = graph_note_diagnostics_service
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._commit_projection = commit_projection
        self._rollback_projection = rollback_projection
        self._relation_mutation = ObsidianRelationMutationService(obsidian_service)
        self._graph_verifier = GraphVerifier(
            graph_service=graph_service,
            graph_repository=graph_repository,
        )

    async def apply(
        self,
        request: ObsidianRelateRequest,
        request_hash: str,
        checkpoint_key: str,
        store: ObsidianReportBundleRunStore,
    ) -> ObsidianRelateResult:
        """Apply a normalized, validated request within its one shared lease.

        Args:
            request: Normalized and validated relation intent.
            request_hash: Stable hash of the closed request identity.
            checkpoint_key: Durable replay key derived by the public service.
            store: One invocation-owned relation checkpoint store.

        Returns:
            Completed, replayed, or degraded relation evidence.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_relate",
            wait=True,
        ):
            checkpoint = await load_checkpoint(store, checkpoint_key)
            if checkpoint is not None and checkpoint.request_hash != request_hash:
                raise ObsidianIdempotencyConflictError()
            source = await self._obsidian_service.read_note(request.source_note_id)
            target = await self._read_target(request.target_note_id)
            if checkpoint is None:
                validate_source_hash(request, source.content_hash)
            if (
                checkpoint is not None
                and source.content_hash != checkpoint.source_content_hash
            ):
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: relation checkpoint source content hash "
                    "drifted before replay"
                )

            source_link_exists = relation_present(source, target, request.relation)
            if checkpoint is not None and not source_link_exists:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: recorded source relationship is absent; "
                    "durable recovery is required before another mutation"
                )
            if checkpoint is not None and source_link_exists:
                verification = await self._graph_verifier.verify(
                    source_note_id=source.note_id,
                    target_note_id=target.note_id,
                    relation=request.relation,
                )
                if (
                    checkpoint.result.completion_status
                    in {
                        ObsidianRelateCompletionStatus.COMPLETED,
                        ObsidianRelateCompletionStatus.REPLAYED,
                    }
                    and not verification.warnings
                    and verification.source_related
                    and verification.target_related
                    and verification.edge_id is not None
                ):
                    replay = replace(
                        checkpoint.result,
                        completion_status=ObsidianRelateCompletionStatus.REPLAYED,
                        replayed=True,
                        source_path=source.relative_path,
                        target_path=target.relative_path,
                        content_hash=source.content_hash,
                        graph_edge_id=verification.edge_id,
                        projection_run_id=verification.projection_run_id,
                        graph_projection_status=verification.projection_status,
                        source_link_verified=True,
                        target_backlink_verified=verification.target_related,
                        related_notes_verified=verification.source_related,
                    )
                    await save_checkpoint(
                        store,
                        checkpoint_key,
                        replace(checkpoint, result=replay),
                    )
                    return replay

            write_result: ObsidianNoteWriteResult | None = None
            mutation_resolved_after_error = False
            projection_committed = False
            if not source_link_exists:
                try:
                    write_result = await self._relation_mutation.relate(
                        source=source,
                        target=target,
                        relation=request.relation,
                        expected_source_hash=request.expected_source_hash,
                    )
                except Exception:
                    try:
                        source_after = await self._obsidian_service.read_note(
                            request.source_note_id
                        )
                        validate_source_hash(request, source_after.content_hash)
                    except Exception:
                        await self._rollback_after_projection_failure()
                        raise
                    if not relation_present(source_after, target, request.relation):
                        await self._rollback_after_projection_failure()
                        raise
                    source = source_after
                    source_link_exists = True
                    mutation_resolved_after_error = True
                else:
                    source = await self._obsidian_service.read_note(
                        request.source_note_id
                    )
                    if not relation_present(source, target, request.relation):
                        await self._rollback_after_projection_failure()
                        raise ObsidianDomainError(
                            "RELATE_READBACK_FAILED: source relation was not persisted"
                        )
                    source_link_exists = True

            try:
                await self._commit_projection()
                projection_committed = True
            except Exception as exc:
                await self._rollback_after_projection_failure()
                source_after = await self._obsidian_service.read_note(
                    request.source_note_id
                )
                if not relation_present(source_after, target, request.relation):
                    raise
                degraded = degraded_commit_result(
                    request=request,
                    source=source_after,
                    target=target,
                    write_result=write_result,
                    relation_issue=issue(
                        code=RelationIssueCode.PROJECTION_COMMIT_FAILED,
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability=RelationIssueCapability.METADATA_AND_EDGE_INDEX,
                        retryable=True,
                        safe_next_action="replay the same idempotency key after database readiness recovers",
                    ),
                )
                await save_checkpoint(
                    store,
                    checkpoint_key,
                    ObsidianRelateCheckpoint(
                        request_hash=request_hash,
                        source_note_id=source_after.note_id,
                        target_note_id=target.note_id,
                        relation=request.relation,
                        source_content_hash=source_after.content_hash,
                        result=degraded,
                    ),
                )
                return degraded

            warnings: list[ObsidianRelateIssue] = []
            if mutation_resolved_after_error:
                warnings.append(
                    issue(
                        code=RelationIssueCode.MUTATION_OUTCOME_RESOLVED,
                        cause="the canonical write raised before its durable outcome was known",
                        affected_capability=RelationIssueCapability.CANONICAL_RELATION_WRITE,
                        retryable=True,
                        safe_next_action="read the source relation and replay the same idempotency key",
                    )
                )

            rebuild_report = None
            try:
                rebuild_report = (
                    await self._graph_note_diagnostics_service.rebuild_note_graph(
                        note_id=source.note_id,
                    )
                )
            except Exception as exc:
                warnings.append(
                    issue(
                        code=RelationIssueCode.GRAPH_PROJECTION_REBUILD_FAILED,
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability=RelationIssueCapability.GRAPH_PROJECTION,
                        retryable=True,
                        safe_next_action="retry the same idempotency key after graph readiness recovers",
                    )
                )

            final_commit_failed = False
            try:
                await self._commit_projection()
            except Exception as exc:
                final_commit_failed = True
                if projection_committed:
                    await self._rollback_after_projection_failure()
                warnings.append(
                    issue(
                        code=RelationIssueCode.DERIVED_INDEX_COMMIT_FAILED,
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability=RelationIssueCapability.METADATA_AND_EDGE_INDEX,
                        retryable=True,
                        safe_next_action="replay the same idempotency key after database readiness recovers",
                    )
                )
                try:
                    source = await self._obsidian_service.read_note(
                        request.source_note_id
                    )
                except (OSError, ObsidianDomainError) as readback_exc:
                    warnings.append(
                        issue(
                            code=RelationIssueCode.DERIVED_INDEX_READBACK_FAILED,
                            cause=f"{type(readback_exc).__name__}: {readback_exc}",
                            affected_capability=RelationIssueCapability.METADATA_AND_EDGE_INDEX,
                            retryable=True,
                            safe_next_action="replay the same idempotency key after source read readiness recovers",
                        )
                    )

            verification = await self._graph_verifier.verify(
                source_note_id=source.note_id,
                target_note_id=target.note_id,
                relation=request.relation,
            )
            warnings.extend(verification.warnings)
            if (
                rebuild_report is not None
                and rebuild_report.projection.status == "failed"
            ):
                warnings.append(
                    issue(
                        code=RelationIssueCode.GRAPH_PROJECTION_REBUILD_FAILED,
                        cause="the graph projection rebuild did not activate a new snapshot",
                        affected_capability=RelationIssueCapability.GRAPH_PROJECTION,
                        retryable=True,
                        safe_next_action="retry the same idempotency key after graph readiness recovers",
                        recovery_run_id=rebuild_report.projection.run_id,
                    )
                )
            if rebuild_report is not None and rebuild_report.projection.issue_total > 0:
                warnings.append(
                    issue(
                        code=RelationIssueCode.GRAPH_PROJECTION_SOURCE_ISSUES,
                        cause=(
                            f"{rebuild_report.projection.issue_total} non-fatal source issue(s) "
                            "were reported during graph projection rebuild"
                        ),
                        affected_capability=RelationIssueCapability.GRAPH_PROJECTION,
                        retryable=True,
                        safe_next_action="inspect graph diagnostics; the requested edge remains independently verified",
                        recovery_run_id=rebuild_report.projection.run_id,
                    )
                )

            result = build_final_relation_result(
                request=request,
                checkpoint=checkpoint,
                source=source,
                target=target,
                write_result=write_result,
                mutation_resolved_after_error=mutation_resolved_after_error,
                source_link_exists=source_link_exists,
                final_commit_failed=final_commit_failed,
                verification=verification,
                rebuild_report=rebuild_report,
                warnings=warnings,
            )
            checkpoint = ObsidianRelateCheckpoint(
                request_hash=request_hash,
                source_note_id=source.note_id,
                target_note_id=target.note_id,
                relation=request.relation,
                source_content_hash=source.content_hash,
                result=result,
            )
            await save_checkpoint(store, checkpoint_key, checkpoint)
            return result

    async def _rollback_after_projection_failure(self) -> None:
        """Preserve the original failure when transaction rollback also fails."""
        try:
            await self._rollback_projection()
        except Exception:
            return

    async def _read_target(self, target_note_id: str) -> ObsidianNote:
        """Read the exact target and reject implicit target creation."""
        try:
            return await self._obsidian_service.read_note(target_note_id)
        except ObsidianNotFoundError as exc:
            raise ObsidianRelateTargetNotFoundError(target_note_id) from exc
