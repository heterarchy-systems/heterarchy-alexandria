"""Durable, idempotent high-level relation orchestration."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial
from typing import cast

import anyio
from pydantic import TypeAdapter

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.service.notes.obsidian_relation_mutation_service import (
    ObsidianRelationMutationService,
    relation_present,
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
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianRelationType,
    ObsidianWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import ObsidianGraphDirection
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
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
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianIdempotencyConflictError,
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.exceptions.obsidian_relation_exceptions import (
    ObsidianRelateInvalidRelationError,
    ObsidianRelateSelfEdgeError,
    ObsidianRelateTargetNotFoundError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject, JSONValue

_CHECKPOINT_ADAPTER = TypeAdapter(ObsidianRelateCheckpoint)


@dataclass(frozen=True, slots=True, kw_only=True)
class _GraphVerification:
    """Bounded graph readback evidence for one directed relation."""

    edge_id: str | None
    projection_run_id: str | None
    projection_status: str
    source_related: bool
    target_related: bool
    warnings: tuple[ObsidianRelateIssue, ...] = ()


class ObsidianRelateService:
    """Coordinate canonical Markdown, indexed edges, Rust projection, and replay."""

    def __init__(
        self,
        *,
        obsidian_service: ObsidianService,
        graph_note_diagnostics_service: ObsidianGraphNoteDiagnosticsService,
        graph_service: ObsidianGraphService,
        graph_repository: IObsidianGraphProjectionRepository,
        vault_config_store: ObsidianVaultConfigStore,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        commit_projection: Callable[[], Awaitable[None]],
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Create one request-scoped relation orchestration owner."""
        self._obsidian_service = obsidian_service
        self._graph_note_diagnostics_service = graph_note_diagnostics_service
        self._graph_service = graph_service
        self._graph_repository = graph_repository
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._commit_projection = commit_projection
        self._rollback_projection = rollback_projection
        self._relation_mutation = ObsidianRelationMutationService(obsidian_service)

    async def relate(self, request: ObsidianRelateRequest) -> ObsidianRelateResult:
        """Relate two existing notes with durable idempotency and graph readback."""
        request = self._normalize_request(request)
        self._validate_request(request)
        request_hash = relate_request_hash(request)
        checkpoint_key = f"relate:{request.idempotency_key}"
        store = ObsidianReportBundleRunStore(
            self._vault_config_store.current().vault_path
        )
        async with self._index_maintenance_coordinator.operation(
            "obsidian_relate",
            wait=True,
        ):
            checkpoint = await self._load_checkpoint(store, checkpoint_key)
            if checkpoint is not None and checkpoint.request_hash != request_hash:
                raise ObsidianIdempotencyConflictError()
            source = await self._obsidian_service.read_note(request.source_note_id)
            target = await self._read_target(request.target_note_id)
            if checkpoint is None:
                self._validate_source_hash(request, source.content_hash)
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
                verification = await self._verify_graph(
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
                    await self._save_checkpoint(
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
                        self._validate_source_hash(request, source_after.content_hash)
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
                degraded = self._degraded_commit_result(
                    request=request,
                    source=source_after,
                    target=target,
                    write_result=write_result,
                    issue=_issue(
                        code="PROJECTION_COMMIT_FAILED",
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability="metadata_and_edge_index",
                        retryable=True,
                        safe_next_action="replay the same idempotency key after database readiness recovers",
                    ),
                )
                await self._save_checkpoint(
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
                    _issue(
                        code="MUTATION_OUTCOME_RESOLVED",
                        cause="the canonical write raised before its durable outcome was known",
                        affected_capability="canonical_relation_write",
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
                    _issue(
                        code="GRAPH_PROJECTION_REBUILD_FAILED",
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability="graph_projection",
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
                    _issue(
                        code="DERIVED_INDEX_COMMIT_FAILED",
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability="metadata_and_edge_index",
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
                        _issue(
                            code="DERIVED_INDEX_READBACK_FAILED",
                            cause=f"{type(readback_exc).__name__}: {readback_exc}",
                            affected_capability="metadata_and_edge_index",
                            retryable=True,
                            safe_next_action="replay the same idempotency key after source read readiness recovers",
                        )
                    )

            verification = await self._verify_graph(
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
                    _issue(
                        code="GRAPH_PROJECTION_REBUILD_FAILED",
                        cause="the graph projection rebuild did not activate a new snapshot",
                        affected_capability="graph_projection",
                        retryable=True,
                        safe_next_action="retry the same idempotency key after graph readiness recovers",
                        recovery_run_id=rebuild_report.projection.run_id,
                    )
                )
            if rebuild_report is not None and rebuild_report.projection.issue_total > 0:
                warnings.append(
                    _issue(
                        code="GRAPH_PROJECTION_SOURCE_ISSUES",
                        cause=(
                            f"{rebuild_report.projection.issue_total} non-fatal source issue(s) "
                            "were reported during graph projection rebuild"
                        ),
                        affected_capability="graph_projection",
                        retryable=True,
                        safe_next_action="inspect graph diagnostics; the requested edge remains independently verified",
                        recovery_run_id=rebuild_report.projection.run_id,
                    )
                )

            operation = (
                write_result.operation
                if write_result is not None
                else ObsidianWriteOperation.UNCHANGED
            )
            result = ObsidianRelateResult(
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
                        else (
                            "indexed" if verification.edge_id is not None else "unknown"
                        )
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
                            None
                            if rebuild_report is None
                            else rebuild_report.projection.run_id
                        )
                    )
                ),
                warnings=tuple(warnings),
            )
            checkpoint = ObsidianRelateCheckpoint(
                request_hash=request_hash,
                source_note_id=source.note_id,
                target_note_id=target.note_id,
                relation=request.relation,
                source_content_hash=source.content_hash,
                result=result,
            )
            await self._save_checkpoint(store, checkpoint_key, checkpoint)
            return result

    async def _load_checkpoint(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
    ) -> ObsidianRelateCheckpoint | None:
        """Load the relation checkpoint through the bounded blocking-I/O lane."""
        return await anyio.to_thread.run_sync(
            partial(store.load_typed, checkpoint_key, _CHECKPOINT_ADAPTER),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def _save_checkpoint(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
        checkpoint: ObsidianRelateCheckpoint,
    ) -> None:
        """Save the relation checkpoint through the bounded blocking-I/O lane."""
        await anyio.to_thread.run_sync(
            partial(
                store.save_typed,
                checkpoint_key,
                checkpoint,
                _CHECKPOINT_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def _rollback_after_projection_failure(self) -> None:
        """Preserve the original failure when transaction rollback also fails."""
        try:
            await self._rollback_projection()
        except Exception:
            return

    @staticmethod
    def _degraded_commit_result(
        *,
        request: ObsidianRelateRequest,
        source: ObsidianNote,
        target: ObsidianNote,
        write_result: ObsidianNoteWriteResult | None,
        issue: ObsidianRelateIssue,
    ) -> ObsidianRelateResult:
        """Return source-preserved evidence when request SQL commit is unknown."""
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
            warnings=(issue,),
        )

    async def _read_target(self, target_note_id: str) -> ObsidianNote:
        """Read the exact target and reject implicit target creation."""
        try:
            return await self._obsidian_service.read_note(target_note_id)
        except ObsidianNotFoundError as exc:
            raise ObsidianRelateTargetNotFoundError(target_note_id) from exc

    async def _verify_graph(
        self,
        *,
        source_note_id: str,
        target_note_id: str,
        relation: ObsidianRelationType,
    ) -> _GraphVerification:
        """Verify exact projected edge plus both graph read directions."""
        warnings: list[ObsidianRelateIssue] = []
        try:
            state = await self._graph_repository.state()
            edge = next(
                (
                    item
                    for item in state.projection.edges
                    if item.source_note_id == source_note_id
                    and item.target_note_id == target_note_id
                    and item.relation is relation
                ),
                None,
            )
        except Exception as exc:
            return _GraphVerification(
                edge_id=None,
                projection_run_id=None,
                projection_status="unavailable",
                source_related=False,
                target_related=False,
                warnings=(
                    _issue(
                        code="GRAPH_PROJECTION_READ_FAILED",
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability="graph_projection",
                        retryable=True,
                        safe_next_action="restore graph projection readiness and replay the same idempotency key",
                    ),
                ),
            )

        source_related = False
        target_related = False
        try:
            source_related = any(
                item.note.note_id == target_note_id
                and item.relation is relation
                and item.direction == ObsidianGraphDirection.OUTGOING.value
                for item in await self._graph_service.related_notes(
                    source_note_id,
                    limit=50,
                )
            )
            target_related = any(
                item.note.note_id == source_note_id
                and item.relation is relation
                and item.direction == ObsidianGraphDirection.INCOMING.value
                for item in await self._graph_service.related_notes(
                    target_note_id,
                    limit=50,
                )
            )
        except Exception as exc:
            warnings.append(
                _issue(
                    code="GRAPH_RELATED_READ_FAILED",
                    cause=str(exc),
                    affected_capability="related_note_read",
                    retryable=True,
                    safe_next_action="restore graph read readiness and replay the same idempotency key",
                )
            )

        projection_status = "ready" if edge is not None else "stale"
        if edge is None:
            warnings.append(
                _issue(
                    code="GRAPH_EDGE_NOT_VERIFIED",
                    cause="the exact directed relation is absent from the active projection",
                    affected_capability="graph_projection",
                    retryable=True,
                    safe_next_action="retry the same idempotency key after graph projection rebuild",
                )
            )
        return _GraphVerification(
            edge_id=None if edge is None else edge.edge_id,
            projection_run_id=state.run_id,
            projection_status=projection_status,
            source_related=source_related,
            target_related=target_related,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _normalize_request(request: ObsidianRelateRequest) -> ObsidianRelateRequest:
        """Normalize and validate optional source CAS hashes for all callers."""
        expected = request.expected_source_hash
        if expected is not None:
            expected = expected.strip().lower()
            if len(expected) != 64 or any(
                character not in "0123456789abcdef" for character in expected
            ):
                raise ObsidianValidationError(
                    "expected_source_hash must be a SHA-256 hexadecimal digest"
                )
        return replace(
            request,
            source_note_id=request.source_note_id.strip(),
            target_note_id=request.target_note_id.strip(),
            idempotency_key=request.idempotency_key.strip(),
            expected_source_hash=expected,
        )

    @staticmethod
    def _validate_request(request: ObsidianRelateRequest) -> None:
        """Reject unsupported relation intent before any read or write."""
        if request.source_note_id == request.target_note_id:
            raise ObsidianRelateSelfEdgeError(request.source_note_id)
        if request.relation is ObsidianRelationType.WIKILINK:
            raise ObsidianRelateInvalidRelationError(request.relation.value)

    @staticmethod
    def _validate_source_hash(request: ObsidianRelateRequest, actual: str) -> None:
        """Apply the caller's explicit source compare-and-swap token."""
        if (
            request.expected_source_hash is not None
            and actual != request.expected_source_hash
        ):
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: expected source content hash does not match "
                "the current note"
            )


def relate_request_hash(request: ObsidianRelateRequest) -> str:
    """Return a deterministic immutable intent hash for replay fencing."""
    payload: JSONObject = {
        "source_note_id": request.source_note_id,
        "target_note_id": request.target_note_id,
        "relation": request.relation.value,
        "expected_source_hash": request.expected_source_hash,
    }
    return hashlib.sha256(dumps_canonical_json(cast(JSONValue, payload))).hexdigest()


def _issue(
    *,
    code: str,
    cause: str,
    affected_capability: str,
    retryable: bool,
    safe_next_action: str,
    recovery_run_id: str | None = None,
) -> ObsidianRelateIssue:
    """Build one bounded actionable relation issue."""
    return ObsidianRelateIssue(
        code=code,
        cause=cause,
        affected_capability=affected_capability,
        retryable=retryable,
        safe_next_action=safe_next_action,
        recovery_run_id=recovery_run_id,
    )
