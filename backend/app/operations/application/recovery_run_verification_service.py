"""Readiness and representative read-back verification for recovery runs."""

from __future__ import annotations

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.operations.application.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.application.recovery_run_contracts import (
    ContextRecoveryService,
    ContextRecoveryServiceFactory,
    ObsidianRecoveryService,
    ObsidianRecoveryServiceFactory,
    resolve_recovery_service,
)
from app.operations.application.recovery_run_source_preservation import (
    _source_preservation_result,
)
from app.operations.domain.entities.recovery_plan import RecoveryPlan
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONObject

_REPRESENTATIVE_QUERY = "운영 안정성 자동 복구 루프"
_REPRESENTATIVE_NOTE_ID = "prd_operational_readiness_recovery_v0_1"
_REPRESENTATIVE_PATH_SUFFIX = (
    "Contexts/Projects/heterarchy-alexandria/dev-size/PRD/"
    "PRD - 운영 안정성 및 자동 복구 루프.md"
)


class RecoveryRunVerificationService:
    """Verify platform readiness, source preservation, search, and read-back."""

    def __init__(
        self,
        *,
        database: Database,
        context_service: ContextRecoveryService,
        obsidian_service: ObsidianRecoveryService,
        context_service_factory: ContextRecoveryServiceFactory | None = None,
        obsidian_service_factory: ObsidianRecoveryServiceFactory | None = None,
    ) -> None:
        """Initialize recovery verification dependencies.

        Args:
            database: Shared database coordinator.
            context_service: Context readiness boundary.
            obsidian_service: Obsidian readiness, search, and read boundary.
        """
        self._database = database
        self._context_service_factory = context_service_factory or (
            lambda: context_service
        )
        self._obsidian_service_factory = obsidian_service_factory or (
            lambda: obsidian_service
        )

    async def verify_readiness(self, plan: RecoveryPlan) -> JSONObject:
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
                ).snapshot()
                representative = await self.verify_representative_search(
                    obsidian_service
                )
            except Exception:
                await session.rollback()
                raise
            await session.commit()
        source_preservation = _source_preservation_result(plan.source_snapshot)
        warnings = list(snapshot.warnings)
        blockers = list(snapshot.blockers)
        if representative["matched"] is not True:
            warnings.append("representative_search_missing")
            blockers.append("representative_search_missing")
        if source_preservation["preserved"] is not True:
            warnings.append("source_markdown_changed")
            blockers.append("source_markdown_changed")
        return {
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

    async def verify_representative_search(
        self,
        obsidian_service: ObsidianRecoveryService,
    ) -> JSONObject:
        hits = await obsidian_service.search(
            ObsidianSearchQuery(query=_REPRESENTATIVE_QUERY, limit=5),
            refresh=True,
        )
        matches: list[JSONObject] = [
            {
                "id": hit.note.note_id,
                "path": hit.note.relative_path,
                "title": hit.note.title,
            }
            for hit in hits
        ]
        matched_path = next(
            (
                str(match["path"])
                for match in matches
                if match["id"] == _REPRESENTATIVE_NOTE_ID
                and str(match["path"]).endswith(_REPRESENTATIVE_PATH_SUFFIX)
            ),
            None,
        )
        readback = await self.verify_representative_readback(
            obsidian_service,
            matched_path,
        )
        matched = matched_path is not None and readback["matched"] is True
        return {
            "query": _REPRESENTATIVE_QUERY,
            "expected_id": _REPRESENTATIVE_NOTE_ID,
            "expected_path_suffix": _REPRESENTATIVE_PATH_SUFFIX,
            "matched": matched,
            "matches": matches,
            "readback": readback,
        }

    async def verify_representative_readback(
        self,
        obsidian_service: ObsidianRecoveryService,
        matched_path: str | None,
    ) -> JSONObject:
        if matched_path is None:
            return {
                "matched": False,
                "id_read": None,
                "path_read": None,
                "error": None,
            }
        try:
            by_id = await obsidian_service.read_note(_REPRESENTATIVE_NOTE_ID)
            by_path = await obsidian_service.read_note_by_path(matched_path)
        except Exception as exc:  # pragma: no cover - exact read failures vary
            return {
                "matched": False,
                "id_read": None,
                "path_read": None,
                "error": str(exc),
            }
        id_read = _representative_readback_note_payload(by_id)
        path_read = _representative_readback_note_payload(by_path)
        return {
            "matched": (
                id_read["id"] == _REPRESENTATIVE_NOTE_ID
                and str(id_read["path"]).endswith(_REPRESENTATIVE_PATH_SUFFIX)
                and path_read["id"] == _REPRESENTATIVE_NOTE_ID
                and str(path_read["path"]).endswith(_REPRESENTATIVE_PATH_SUFFIX)
                and id_read["path"] == path_read["path"]
            ),
            "id_read": id_read,
            "path_read": path_read,
            "error": None,
        }


def _representative_readback_note_payload(note: ObsidianNote) -> JSONObject:
    return {
        "id": note.note_id,
        "path": note.relative_path,
        "title": note.title,
        "content_hash": note.content_hash,
    }
