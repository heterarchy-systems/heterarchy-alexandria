"""Mutation operations executed by an operational recovery run."""

from __future__ import annotations

from collections.abc import Mapping

from app.memory.application.contexts.records.context_service_ports import (
    ContextRecoveryPort,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianRecoveryPort
from app.operations.application.recovery.execution.recovery_run_contracts import (
    ContextRecoveryPortFactory,
    EmbeddingRecoveryCallback,
    ObsidianRecoveryPortFactory,
    RecoveryDiagnosticCallback,
    resolve_recovery_service,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianDomainError
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONObject
from app.shared.utils.secret_redaction import redact_secret_text


class RecoveryRunMutationOperations:
    """Execute destructive and rebuild steps through explicit service boundaries."""

    def __init__(
        self,
        database: Database,
        context_service: ContextRecoveryPort,
        obsidian_service: ObsidianRecoveryPort,
        context_service_factory: ContextRecoveryPortFactory | None = None,
        obsidian_service_factory: ObsidianRecoveryPortFactory | None = None,
        embedding_recovery_callback: EmbeddingRecoveryCallback | None = None,
        graph_rebuild_callback: RecoveryDiagnosticCallback | None = None,
        link_diagnostics_callback: RecoveryDiagnosticCallback | None = None,
        dlq_reconcile_callback: RecoveryDiagnosticCallback | None = None,
        embedding_batch_size: int = 250,
        embedding_max_batches: int = 40,
    ) -> None:
        """Initialize recovery mutation dependencies.

        Args:
            database: Shared database coordinator.
            context_service: Context embedding recovery boundary.
            obsidian_service: Obsidian index recovery boundary.
            context_service_factory: Factory that creates context service.
            obsidian_service_factory: Factory that creates obsidian service.
        """
        self._database = database
        self._context_service_factory = context_service_factory or (
            lambda: context_service
        )
        self._obsidian_service_factory = obsidian_service_factory or (
            lambda: obsidian_service
        )
        self._embedding_recovery_callback = embedding_recovery_callback
        self._graph_rebuild_callback = graph_rebuild_callback
        self._link_diagnostics_callback = link_diagnostics_callback
        self._dlq_reconcile_callback = dlq_reconcile_callback
        self._embedding_batch_size = embedding_batch_size
        self._embedding_max_batches = embedding_max_batches

    async def reindex_vault(self) -> JSONObject:
        """Reindex the Obsidian vault.

        Returns:
            Reindex operation result.
        """
        async with self._database.request_session() as session:
            try:
                service = await resolve_recovery_service(self._obsidian_service_factory)
                result = await service.reindex()
            except Exception:
                await session.rollback()
                raise
            await session.commit()
        return {
            "files_seen": result.files_seen,
            "files_indexed": result.files_indexed,
            "files_skipped": result.files_skipped,
            "stale_marked": result.stale_marked,
            "errors": list(result.errors),
            "plan_fingerprint": result.plan_fingerprint,
            "policy_version": result.policy_version,
            "embedding_invalidated_documents": result.embedding_invalidated_documents,
            "diagnostic_count": result.diagnostic_count,
        }

    async def repair_error_notes(
        self, paths: tuple[str, ...], source_manifest: Mapping[str, str] | None = None
    ) -> JSONObject:
        """Re-parse and revalidate each index-error note in place.

        Bounded note-local repair: listed index rows are refreshed; known invalid
        managed hashes are repaired behind the preview source CAS without changing bodies.
        Notes whose source no longer parses are reported for manual agent
        repair instead of failing the whole lane silently.

        Args:
            paths: Bounded vault-relative error-note paths from the plan.
            source_manifest: Planned exact repair hashes alongside inventory tokens.

        Returns:
            Repaired and requires-manual-repair evidence lists.
        """
        repaired: list[JSONObject] = []
        requires_manual_repair: list[JSONObject] = []
        for note_path in paths:
            try:
                # Independent source repairs keep independent transaction evidence;
                # a failed note must not roll back earlier successful index repairs.
                async with self._database.request_session() as session:
                    service = await resolve_recovery_service(
                        self._obsidian_service_factory
                    )
                    token = (
                        None
                        if source_manifest is None
                        else source_manifest.get(note_path)
                    )
                    if token is not None and token.startswith("sha256:"):
                        note = await service.revalidate_note_index(
                            path=note_path,
                            expected_source_hash=token.removeprefix("sha256:"),
                        )
                    else:
                        note = await service.revalidate_note_index(path=note_path)
                    await session.commit()
            except Exception as exc:
                diagnostic = (
                    redact_secret_text(str(exc))
                    if isinstance(exc, (ObsidianDomainError, ValueError))
                    else None
                )
                requires_manual_repair.append(
                    {
                        "path": note_path,
                        "error": type(exc).__name__
                        if diagnostic is None or diagnostic.blocked
                        else diagnostic.redacted_content[:200],
                    }
                )
                continue
            repaired.append(
                {
                    "path": note_path,
                    "note_id": note.note_id,
                    "content_hash": note.content_hash,
                }
            )
        return {
            "repaired": repaired,
            "requires_manual_repair": requires_manual_repair,
        }

    async def reindex_embeddings(self) -> JSONObject:
        """Reindex context embeddings.

        Returns:
            Reindex operation result.
        """
        async with self._database.request_session() as session:
            callback_result: JSONObject | None = None
            try:
                service = await resolve_recovery_service(self._context_service_factory)
                if self._embedding_recovery_callback is not None:
                    callback_result = await self._embedding_recovery_callback(
                        service,
                        self._embedding_batch_size,
                        self._embedding_max_batches,
                    )
                    batches = callback_result.get("batches")
                    if not isinstance(batches, list):
                        raise RuntimeError("EMBEDDING_RECOVERY_BATCH_EVIDENCE_MISSING")
                    if len(batches) > self._embedding_max_batches:
                        raise RuntimeError("EMBEDDING_RECOVERY_BATCH_BOUND_EXCEEDED")
                    result = None
                else:
                    result = await service.reindex_embeddings(
                        limit=self._embedding_batch_size,
                        force=False,
                    )
            except Exception:
                await session.rollback()
                raise
            await session.commit()
        if callback_result is not None:
            return callback_result
        if result is None:
            raise RuntimeError("EMBEDDING_REINDEX_EMPTY_RESULT")
        return {
            "scanned": result.scanned,
            "updated": result.updated,
            "skipped": result.skipped,
            "warnings": list(result.warnings),
        }

    async def revalidate_graph(self) -> JSONObject:
        """Rebuild the existing PostgreSQL graph projection owner."""
        if self._graph_rebuild_callback is None:
            raise RuntimeError("GRAPH_REBUILD_UNAVAILABLE: graph owner is not wired")
        return await self._graph_rebuild_callback()

    async def revalidate_links(self) -> JSONObject:
        """Read bounded graph/link diagnostics without repairing links."""
        if self._link_diagnostics_callback is None:
            raise RuntimeError(
                "LINK_DIAGNOSTICS_UNAVAILABLE: graph issue reader is not wired"
            )
        return await self._link_diagnostics_callback()

    async def reconcile_dead_letters(self) -> JSONObject:
        """Read maintenance dead-letter evidence without retrying effects."""
        if self._dlq_reconcile_callback is None:
            raise RuntimeError("DLQ_RECONCILE_UNAVAILABLE: DLQ reader is not wired")
        return await self._dlq_reconcile_callback()
