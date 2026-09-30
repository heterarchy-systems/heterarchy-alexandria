"""Readiness and representative read-back verification for recovery runs."""

from __future__ import annotations

from pathlib import Path

import anyio
import anyio.to_thread

from app.memory.application.contexts.records.context_service_ports import (
    ContextRecoveryPort,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianRecoveryPort
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.operations.application.readiness.operational_readiness_service import (
    GraphProjectionReadinessPort,
    OperationalReadinessService,
)
from app.operations.application.recovery.execution.recovery_run_contracts import (
    ContextRecoveryPortFactory,
    ObsidianRecoveryPortFactory,
    RecoveryDiagnosticCallback,
    resolve_recovery_service,
)
from app.operations.application.recovery.execution.recovery_run_source_preservation import (
    _source_preservation_result,
)
from app.operations.domain.entities.recovery_plan import RecoveryPlan
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONObject


class RecoveryRunVerificationService:
    """Verify platform readiness, source preservation, search, and read-back."""

    def __init__(
        self,
        database: Database,
        context_service: ContextRecoveryPort,
        obsidian_service: ObsidianRecoveryPort,
        context_service_factory: ContextRecoveryPortFactory | None = None,
        obsidian_service_factory: ObsidianRecoveryPortFactory | None = None,
        *,
        graph_projection_service: GraphProjectionReadinessPort,
        current_compact_reader_callback: RecoveryDiagnosticCallback | None = None,
    ) -> None:
        """Initialize recovery verification dependencies.

        Args:
            database: Shared database coordinator.
            context_service: Context readiness boundary.
            obsidian_service: Obsidian readiness, search, and read boundary.
            context_service_factory: Factory that creates context service.
            obsidian_service_factory: Factory that creates obsidian service.
            graph_projection_service: Graph projection status boundary.
        """
        self._database = database
        self._context_service_factory = context_service_factory or (
            lambda: context_service
        )
        self._obsidian_service_factory = obsidian_service_factory or (
            lambda: obsidian_service
        )
        self._graph_projection_service = graph_projection_service
        self._current_compact_reader_callback = current_compact_reader_callback

    async def verify_readiness(
        self,
        plan: RecoveryPlan,
        *,
        compile_receipt_required: bool = False,
        expected_compile_policy_version: str | None = None,
        expected_compile_plan_fingerprint: str | None = None,
    ) -> JSONObject:
        """Verify runtime readiness.

        Args:
            plan: Recovery or repair plan being verified or serialized.

        Returns:
            Verification result.
        """
        async with self._database.request_session() as session:
            try:
                context_service = await resolve_recovery_service(
                    self._context_service_factory
                )
                obsidian_service = await resolve_recovery_service(
                    self._obsidian_service_factory
                )
                snapshot = await OperationalReadinessService(
                    database=self._database,
                    context_service=context_service,
                    obsidian_service=obsidian_service,
                    ignore_active_recovery_run_id=plan.id,
                    graph_projection_service=self._graph_projection_service,
                    compile_receipt_required=compile_receipt_required,
                    expected_compile_policy_version=expected_compile_policy_version,
                    expected_compile_plan_fingerprint=expected_compile_plan_fingerprint,
                ).snapshot()
                source_path = plan.source_snapshot.representative_path
                relative_path = (
                    None
                    if source_path is None
                    else str(
                        Path(source_path).relative_to(plan.source_snapshot.vault_path)
                    )
                )
                representative = await self.verify_representative_search(
                    obsidian_service, relative_path
                )
            except Exception:
                await session.rollback()
                raise
            await session.commit()
        source_preservation = await anyio.to_thread.run_sync(
            _source_preservation_result,
            plan.source_snapshot,
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
        warnings = list(snapshot.warnings)
        blockers = list(snapshot.blockers)
        if representative["matched"] is not True:
            warnings.append("representative_search_missing")
            blockers.append("representative_search_missing")
        if source_preservation["preserved"] is not True:
            warnings.append("source_markdown_changed")
            blockers.append("source_markdown_changed")
        result: JSONObject = {
            "status": snapshot.status.value,
            "ready": (
                snapshot.ready
                and representative["matched"] is True
                and source_preservation["preserved"] is True
            ),
            "warnings": warnings,
            "blockers": blockers,
            "source_preservation": source_preservation,
            "representative_search": representative,
        }
        if self._current_compact_reader_callback is not None:
            try:
                result[
                    "current_compact"
                ] = await self._current_compact_reader_callback()
            except Exception as exc:  # pragma: no cover - provider-specific errors
                result["current_compact"] = {
                    "available": False,
                    "error": type(exc).__name__,
                }
                result["warnings"] = [
                    *warnings,
                    "current_compact_unavailable",
                ]
                result["blockers"] = [
                    *blockers,
                    "current_compact_unavailable",
                ]
                result["ready"] = False
        return result

    async def verify_representative_search(
        self,
        obsidian_service: ObsidianRecoveryPort,
        source_path: str | None,
    ) -> JSONObject:
        """Verify actual admitted source retrieval and exact identity read-back.

        Args:
            obsidian_service: Canonical search/read owner.
            source_path: Representative managed path from the admitted snapshot.

        Returns:
            Bounded search evidence and canonical id/path/body match.
        """
        if source_path is None:
            return {
                "matched": False,
                "matches": [],
                "error": "representative_source_missing",
            }
        try:
            source = await obsidian_service.read_note_by_path(source_path)
            hits = await obsidian_service.search(
                ObsidianSearchQuery(query=source.title[:255], limit=5),
                refresh=True,
            )
            by_id = await obsidian_service.read_note(source.note_id)
        except Exception as exc:
            return {"matched": False, "matches": [], "error": type(exc).__name__}
        return {
            "query": source.title[:255],
            "expected_id": source.note_id,
            "expected_path": source_path,
            "matched": any(
                hit.note.note_id == source.note_id
                and hit.note.relative_path == source_path
                for hit in hits
            )
            and by_id.relative_path == source_path
            and by_id.content_hash == source.content_hash,
            "matches": [
                {
                    "id": hit.note.note_id,
                    "path": hit.note.relative_path,
                    "title": hit.note.title,
                }
                for hit in hits
            ],
            "readback": {
                "id_read": _representative_readback_note_payload(by_id),
                "path_read": _representative_readback_note_payload(source),
            },
        }


def _representative_readback_note_payload(note: ObsidianNote) -> JSONObject:
    """Serialize exact canonical identity and body digest for verification.

    Args:
        note: Canonical note read by its owning service.

    Returns:
        Bounded source identity evidence.
    """
    return {
        "id": note.note_id,
        "path": note.relative_path,
        "title": note.title,
        "content_hash": note.content_hash,
    }
