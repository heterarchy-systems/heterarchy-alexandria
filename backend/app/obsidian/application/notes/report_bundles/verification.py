"""Read-only duplicate and incoming-edge verification for report bundles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.obsidian.application.notes.report_bundles.obsidian_report_bundle_identity import (
    same_report_content,
    same_report_identity,
)
from app.obsidian.application.notes.report_bundles.report_bundle_enums import (
    ReportBundleMarker,
)
from app.obsidian.application.notes.report_bundles.results import operation_error
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphDirection,
)
from app.obsidian.domain.policies.obsidian_source_scan_policy import (
    DEFAULT_SOURCE_SCAN_LIMIT,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianValidationError,
)
from app.shared.types.extra_types import JSONObject

if TYPE_CHECKING:
    from app.obsidian.application.graph.obsidian_graph_service import (
        ObsidianGraphService,
    )
    from app.obsidian.application.service.obsidian_service import ObsidianService


class ReportBundleVerifier:
    """Perform the two existing read-only report-bundle verification queries."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        graph_service: ObsidianGraphService,
    ) -> None:
        """Bind verification to canonical source and graph read services.

        Args:
            obsidian_service: Canonical source snapshot owner.
            graph_service: Existing graph read owner.
        """
        self._obsidian_service = obsidian_service
        self._graph_service = graph_service

    async def duplicate_paths(
        self,
        request: ObsidianReportBundleRequest,
        source: ObsidianNote,
    ) -> tuple[str, ...]:
        """Find exact content or declared report-identity duplicates.

        Args:
            request: Normalized request defining the expected source path.
            source: Canonical source note written for the bundle.

        Returns:
            Sorted vault-relative paths of duplicate notes.
        """
        duplicates: set[str] = set()
        requested_path = request.source.relative_path
        if requested_path is not None and source.relative_path != requested_path:
            duplicates.add(source.relative_path)
        snapshot = await self._obsidian_service.source_snapshot(
            max_notes=DEFAULT_SOURCE_SCAN_LIMIT
        )
        if not snapshot.complete or snapshot.errors:
            raise ObsidianValidationError(
                "DUPLICATE_SOURCE_SNAPSHOT_INCOMPLETE: duplicate verification "
                "requires a complete bounded canonical source snapshot"
            )
        for item in snapshot.notes:
            if item.note_id == source.note_id:
                continue
            if same_report_content(source, item) or same_report_identity(source, item):
                duplicates.add(item.relative_path)
        return tuple(sorted(duplicates))

    async def incoming_edges(
        self,
        source_note_id: str,
        expected_owner_ids: set[str],
    ) -> tuple[set[str], tuple[JSONObject, ...]]:
        """Read the bounded active graph neighborhood for incoming owner edges.

        Args:
            source_note_id: Canonical report-source identifier to inspect.
            expected_owner_ids: Owner note identifiers expected in the readback.

        Returns:
            Verified incoming owner identifiers and accumulated read errors.
        """
        try:
            related = await self._graph_service.related_notes(
                source_note_id,
                limit=max(10, len(expected_owner_ids) * 4),
            )
        except ObsidianDomainError as exc:
            return set(), (
                operation_error(
                    function=ReportBundleMarker.GRAPH_RELATION_LOOKUP.value,
                    error=exc,
                ),
            )
        verified_owner_ids = {
            item.note.note_id
            for item in related
            if item.direction == ObsidianGraphDirection.INCOMING.value
            and item.note.note_id in expected_owner_ids
        }
        return verified_owner_ids, ()
