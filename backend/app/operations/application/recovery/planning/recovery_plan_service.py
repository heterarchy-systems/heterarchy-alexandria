"""Read-only recovery dry-run planning service."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from shutil import disk_usage
from uuid import NAMESPACE_URL, uuid5

import anyio
import anyio.to_thread

from app.memory.application.contexts.records.context_service_ports import (
    ContextReadinessPort,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_ports import (
    MemoryReconciliationReadinessPort,
)
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianReadinessPort,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    validate_discovered_note_path,
)
from app.operations.application.readiness.operational_readiness_service import (
    GraphProjectionReadinessPort,
    OperationalReadinessService,
)
from app.operations.application.recovery.execution.recovery_run_contracts import (
    EmbeddingRecoveryCallback,
    RecoveryDiagnosticCallback,
)
from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.application.recovery.planning.recovery_plan_policy import (
    blocked_reasons as _collect_blocked_reasons,
    bounded_error_note_paths,
    default_idempotency_key,
    diagnosis,
    missing_step_capabilities,
    next_actions,
    plan_hash,
    plan_status,
    steps as _build_steps,
)
from app.operations.application.recovery.planning.recovery_plan_source_policy import (
    file_sha256,
    source_snapshot as _build_source_snapshot,
)
from app.operations.domain.entities.recovery_plan import RecoveryPlan
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.shared.infrastructure.database import Database

__all__ = (
    "RecoveryPlanRequest",
    "RecoveryPlanService",
)


class RecoveryPlanService:
    """Build read-only recovery plans without moving or deleting files."""

    def __init__(
        self,
        database: Database,
        context_service: ContextReadinessPort,
        obsidian_service: ObsidianReadinessPort,
        reconciliation_service: MemoryReconciliationReadinessPort | None = None,
        *,
        graph_projection_service: GraphProjectionReadinessPort,
        embedding_recovery_callback: EmbeddingRecoveryCallback | None = None,
        graph_rebuild_callback: RecoveryDiagnosticCallback | None = None,
        link_diagnostics_callback: RecoveryDiagnosticCallback | None = None,
        dlq_reconcile_callback: RecoveryDiagnosticCallback | None = None,
        current_compact_reader_callback: RecoveryDiagnosticCallback | None = None,
    ) -> None:
        """Create service.

        Args:
            database: Shared database coordinator.
            context_service: Context/RAG service.
            obsidian_service: Obsidian vault service.
            reconciliation_service: Optional memory reconciliation diagnostics.
            graph_projection_service: Graph projection status boundary.
            embedding_recovery_callback: Existing bounded embedding recovery owner.
            graph_rebuild_callback: Existing graph projection rebuild owner.
            link_diagnostics_callback: Existing bounded graph issue reader.
            dlq_reconcile_callback: Existing read-only DLQ reconciler.
            current_compact_reader_callback: Existing CURRENT compact reader.
        """
        self._database = database
        self._context_service = context_service
        self._obsidian_service = obsidian_service
        self._reconciliation_service = reconciliation_service
        self._graph_projection_service = graph_projection_service
        self._embedding_recovery_callback = embedding_recovery_callback
        self._graph_rebuild_callback = graph_rebuild_callback
        self._link_diagnostics_callback = link_diagnostics_callback
        self._dlq_reconcile_callback = dlq_reconcile_callback
        self._current_compact_reader_callback = current_compact_reader_callback

    async def plan(self, request: RecoveryPlanRequest) -> RecoveryPlan:
        """Return a read-only recovery dry-run plan.

        Args:
            request: Recovery plan input contract.

        Returns:
            Recovery dry-run plan.
        """
        readiness_service = OperationalReadinessService(
            database=self._database,
            context_service=self._context_service,
            obsidian_service=self._obsidian_service,
            reconciliation_service=self._reconciliation_service,
            graph_projection_service=self._graph_projection_service,
        )
        readiness = await readiness_service.snapshot()
        if self._dlq_reconcile_callback is not None:
            try:
                dlq = await self._dlq_reconcile_callback()
            except Exception:
                readiness = replace(
                    readiness,
                    warnings=(*readiness.warnings, "maintenance_dlq_unknown_outcome"),
                )
            else:
                entries = dlq.get("entries")
                if isinstance(entries, list) and entries:
                    readiness = replace(
                        readiness,
                        warnings=(*readiness.warnings, "maintenance_dlq_present"),
                    )
                if dlq.get("ready") is not True:
                    readiness = replace(
                        readiness,
                        warnings=(
                            *readiness.warnings,
                            "maintenance_dlq_unknown_outcome",
                        ),
                    )
        created_at = datetime.now(UTC)
        idempotency_key = request.idempotency_key or default_idempotency_key(
            trigger=request.trigger,
            actor=request.actor,
        )
        run_id = str(
            uuid5(
                NAMESPACE_URL,
                f"heterarchy-alexandria:recovery:postgresql:{idempotency_key}",
            )
        )
        source_snapshot = await anyio.to_thread.run_sync(
            partial(
                _build_source_snapshot,
                vault_path=readiness.vault.vault_path,
                alexandria_root=readiness.vault.alexandria_root,
                disk_usage_provider=disk_usage,
            ),
        )
        blocked_reasons = _collect_blocked_reasons(
            readiness,
            source_snapshot,
        )
        error_note_repairs: list[str] = []
        if readiness.database.reachable:
            vault_status = await self._obsidian_service.status()
            error_note_repairs = bounded_error_note_paths(
                [error.note_path for error in vault_status.index_errors]
            )
        # Hash only the bounded effect targets; the rest of the inventory keeps
        # its cheap metadata tokens. The existing plan hash now binds exact
        # repair bytes without rereading the entire Vault.
        manifest = dict(source_snapshot.markdown_manifest)
        for path in error_note_repairs:
            absolute = validate_discovered_note_path(
                Path(readiness.vault.vault_path),
                readiness.vault.alexandria_root,
                resolve_note_path(readiness.vault.vault_path, path),
            )
            source_hash = await anyio.to_thread.run_sync(file_sha256, absolute)
            if source_hash is not None:
                manifest[path] = "sha256:" + source_hash
        source_snapshot = replace(source_snapshot, markdown_manifest=manifest)
        steps = _build_steps(readiness, error_note_paths=error_note_repairs)
        blocked_reasons.extend(
            missing_step_capabilities(
                steps,
                embedding_recovery_available=(
                    self._embedding_recovery_callback is not None
                ),
                graph_rebuild_available=self._graph_rebuild_callback is not None,
                link_diagnostics_available=self._link_diagnostics_callback is not None,
                dlq_reconcile_available=self._dlq_reconcile_callback is not None,
                current_compact_reader_available=(
                    self._current_compact_reader_callback is not None
                ),
            )
        )
        status = plan_status(readiness, blocked_reasons)
        has_automatic_repair = any(step.mutates_state for step in steps)
        automatic_execution_allowed = (
            self._database.is_postgresql
            and readiness.database.reachable
            and (has_automatic_repair or readiness.ready)
            and not blocked_reasons
        )
        if automatic_execution_allowed and has_automatic_repair:
            status = OperationalReadinessStatus.RECOVERY_REQUIRED
        return RecoveryPlan(
            id=run_id,
            parent_run_id=request.parent_run_id,
            idempotency_key=idempotency_key,
            trigger=request.trigger,
            actor=request.actor,
            status=status,
            created_at=created_at,
            dry_run=True,
            automatic_execution_allowed=automatic_execution_allowed,
            diagnosis=tuple(diagnosis(readiness)),
            blocked_reasons=tuple(blocked_reasons),
            source_snapshot=source_snapshot,
            steps=tuple(steps),
            plan_hash=plan_hash(
                planned_steps=steps,
                diagnosis=diagnosis(readiness),
                source_snapshot=source_snapshot,
            ),
            error_note_repairs=tuple(error_note_repairs),
            estimated_reindex_scope={
                "vault_indexed_notes": readiness.vault.indexed_notes,
                "managed_markdown_count": source_snapshot.managed_markdown_count,
                "embedding_strategy": readiness.rag.effective_strategy.value,
            },
            service_impact=(
                (
                    "search_blocked_until_verify"
                    if automatic_execution_allowed
                    else "no_mutation_planned"
                ),
            ),
            next_actions=tuple(
                next_actions(
                    status,
                    blocked_reasons,
                    list(readiness.warnings),
                )
            ),
            readiness=readiness,
            warnings=tuple(readiness.warnings),
        )
