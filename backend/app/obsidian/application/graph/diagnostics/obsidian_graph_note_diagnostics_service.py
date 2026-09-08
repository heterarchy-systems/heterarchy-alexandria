"""Per-note diagnostics for indexed Obsidian graph links."""

from __future__ import annotations

from typing import cast

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_support import (
    ObsidianGraphNoteIndexDiagnostic,
    ObsidianGraphNoteLinkValidationReport,
    ObsidianGraphNoteRebuildReport,
    ObsidianGraphNoteSelector,
    ObsidianGraphOutgoingLinkDiagnostic,
    _outgoing_diagnostics,
    _selector,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.obsidian.domain.repositories.obsidian_graph_projection_source_repository import (
    IObsidianGraphProjectionSourceRepository,
)
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


class ObsidianGraphNoteDiagnosticsService:
    """Validate one note's cached outgoing graph links without mutation."""

    def __init__(
        self,
        repository: IObsidianIndexQueryRepository,
        source: IObsidianGraphProjectionSourceRepository,
        projection_service: ObsidianGraphProjectionRebuildService,
        vault_config_store: ObsidianVaultConfigStore | None = None,
        index_maintenance_coordinator: IndexMaintenanceCoordinator | None = None,
    ) -> None:
        """Create per-note graph diagnostics service.

        Args:
            repository: Indexed-note query repository.
            source: Read-only graph projection source rows.
            projection_service: Existing graph projection status provider.
            vault_config_store: Vault config store used by this operation.
            index_maintenance_coordinator: Index maintenance coordinator used by this operation.
        """
        self._repository = repository
        self._source = source
        self._projection_service = projection_service
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = index_maintenance_coordinator

    async def build_status(self) -> ObsidianGraphProjectionStatusReport:
        """Return the current snapshot projection status without rebuilding.

        Returns:
            Existing PostgreSQL graph projection status report.
        """
        return await self._projection_service.status()

    async def validate_note_links(
        self,
        note_id: str | None = None,
        path: str | None = None,
        include_resolved_targets: bool = False,
    ) -> ObsidianGraphNoteLinkValidationReport:
        """Validate cached outgoing graph links for one exact note selector.

        Args:
            note_id: Stable note id selector.
            path: Vault-relative exact path selector.
            include_resolved_targets: Include resolved edge details in addition to
                always-exposed unresolved details.

        Returns:
            Per-note graph diagnostics plus existing projection status.
        """
        selector = _selector(note_id=note_id, path=path)
        note = await self._selected_note(selector)
        projection_status = await self.build_status()
        if note is None:
            return ObsidianGraphNoteLinkValidationReport(
                selector=selector,
                note=ObsidianGraphNoteIndexDiagnostic(exists=False),
                outgoing=ObsidianGraphOutgoingLinkDiagnostic(
                    parsed_count=0,
                    resolved_count=0,
                    unresolved_count=0,
                ),
                projection_status=projection_status,
            )
        notes = await self._source.list_projection_notes()
        edges = tuple(
            edge
            for edge in await self._source.list_projection_edges()
            if edge.source_note_id == note.note_id
        )
        outgoing = _outgoing_diagnostics(
            edges,
            notes=notes,
            include_resolved_targets=include_resolved_targets,
        )
        return ObsidianGraphNoteLinkValidationReport(
            selector=selector,
            note=ObsidianGraphNoteIndexDiagnostic(
                exists=True,
                note_id=note.note_id,
                relative_path=note.relative_path,
                title=note.title,
                index_status=note.index_status.value,
                error_message=note.error_message,
                projection_included=note.index_status is ObsidianIndexStatus.INDEXED,
            ),
            outgoing=outgoing,
            projection_status=projection_status,
        )

    async def rebuild_note_graph(
        self,
        note_id: str | None = None,
        path: str | None = None,
        replace_existing_edges: bool = True,
    ) -> ObsidianGraphNoteRebuildReport:
        """Reparse one canonical note's edges, then activate a full projection.

        Args:
            note_id: Value supplied to rebuild_note_graph.
            path: Value supplied to rebuild_note_graph.
            replace_existing_edges: Value supplied to rebuild_note_graph.

        Returns:
            Result produced by rebuild_note_graph.
        """
        if not replace_existing_edges:
            raise ObsidianValidationError(
                "replace_existing_edges=false is unsupported for canonical edge rebuilds"
            )
        if (
            self._vault_config_store is None
            or self._index_maintenance_coordinator is None
        ):
            raise ObsidianValidationError("note graph rebuild is not configured")
        selector = _selector(note_id=note_id, path=path)
        note = await self._selected_note(selector)
        if note is None:
            raise ObsidianNotFoundError("Obsidian note graph target was not found")
        config = self._vault_config_store.current()
        absolute = resolve_note_path(config.vault_path, note.relative_path)
        payload = note_index_from_path(
            absolute,
            note.relative_path,
            alexandria_root=config.alexandria_root,
        )
        if payload is None:
            raise ObsidianValidationError(
                "Obsidian note is missing Alexandria frontmatter"
            )
        write_repository = cast(IObsidianIndexRepository, self._repository)
        async with self._index_maintenance_coordinator.operation("note_graph_rebuild"):
            await write_repository.upsert_note(payload)
            await write_repository.resolve_edge_targets()
        projection = await self._projection_service.rebuild(
            include_issue_details=True,
        )
        validation = await self.validate_note_links(
            note_id=note.note_id,
            include_resolved_targets=True,
        )
        return ObsidianGraphNoteRebuildReport(
            replace_existing_edges=True,
            validation=validation,
            projection=projection,
        )

    async def _selected_note(
        self,
        selector: ObsidianGraphNoteSelector,
    ) -> ObsidianNote | None:
        """Execute selected note.

        Args:
            selector: Selector used by this operation.

        Returns:
            ObsidianNote | None result produced by selected note.
        """
        note_by_id = (
            await self._repository.get_by_id(selector.note_id)
            if selector.note_id is not None
            else None
        )
        note_by_path = (
            await self._repository.get_by_path(selector.path)
            if selector.path is not None
            else None
        )
        if note_by_id is not None and note_by_path is not None:
            if note_by_id.note_id != note_by_path.note_id:
                raise ObsidianValidationError(
                    "note_id and path selectors refer to different Obsidian notes"
                )
            return note_by_id
        return note_by_id or note_by_path
