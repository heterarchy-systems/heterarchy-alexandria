"""Deterministic graph orphan census and relation suggestions.

``graph issue=0`` only means no missing or ambiguous targets; degree-zero
semantic orphans are invisible to it. This service enumerates orphaned nodes
from the graph projection snapshot, distinguishes notes whose own metadata
still declares relations, and proposes evidence-backed relation candidates.
Suggestions are informational only; nothing is auto-related.
"""

from __future__ import annotations

from app.obsidian.application.graph.diagnostics.orphan_census.checkpoints import (
    OrphanCensusCheckpointStore,
    utc_now,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianReadPort
from app.obsidian.domain.contracts.obsidian_graph_diagnostics_contracts import (
    ObsidianGraphDiagnosticEdge,
    ObsidianGraphDiagnosticNote,
    ObsidianGraphOrphanDiagnosticRequest,
    ObsidianGraphSuggestionDiagnosticRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.entities.obsidian_orphan_census import (
    ObsidianGraphOrphanCensusResult,
    ObsidianGraphOrphanEntry,
    ObsidianGraphRelationSuggestion,
    ObsidianGraphRelationSuggestionsResult,
    ObsidianOrphanAcknowledgement,
    OrphanDecision,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianRelationType
from app.obsidian.domain.repositories.obsidian_graph_diagnostics_compute_provider import (
    IObsidianGraphDiagnosticsComputeProvider,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianNotFoundError,
    ObsidianValidationError,
)


def _relation_field(relation: ObsidianRelationType) -> str | None:
    """Mirror the canonical frontmatter field mapping for relation kinds."""
    if relation is ObsidianRelationType.CITES:
        return "source_ref_links"
    if relation is ObsidianRelationType.WIKILINK:
        return None
    return relation.value


_RELATION_FIELD_NAMES: frozenset[str] = frozenset(
    field
    for field in (_relation_field(relation) for relation in ObsidianRelationType)
    if field is not None
)


class ObsidianGraphOrphanCensusService:
    """Enumerate graph debt and record bounded census provenance."""

    def __init__(
        self,
        graph_repository: IObsidianGraphProjectionRepository,
        vault_config_store: ObsidianVaultConfigStore,
        compute_provider: IObsidianGraphDiagnosticsComputeProvider,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        source_reader: ObsidianReadPort,
    ) -> None:
        """Initialize the bounded graph diagnostic census boundary.

        Args:
            graph_repository: Graph projection snapshot reader.
            vault_config_store: Vault location authority for the durable
                acknowledgement store.
            compute_provider: Rust-owned graph diagnostics provider.
            index_maintenance_coordinator: Shared cross-process diagnostic lease.
            source_reader: Canonical Obsidian read port for exact suggestions.
        """
        self._graph_repository = graph_repository
        self._checkpoints = OrphanCensusCheckpointStore(vault_config_store)
        self._compute_provider = compute_provider
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._source_reader = source_reader

    async def list_orphans(
        self,
        *,
        project: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        index_repository: IObsidianIndexRepository | None = None,
    ) -> ObsidianGraphOrphanCensusResult:
        """Return one bounded, deterministically ordered orphan page.

        Args:
            project: Optional project filter.
            limit: Maximum orphans on this page (1..200).
            cursor: Last path from the previous page.
            index_repository: Session-scoped index reader used to inspect each
                orphan's declared relation metadata; optional so the census
                works without index metadata (declared-relation flags then
                stay unknown-false).

        Returns:
            One census page plus the total orphan count. The bounded
            first/last-seen diagnostic checkpoint is updated under the shared
            maintenance lease.
        """
        if not 1 <= limit <= 200:
            raise ObsidianValidationError("orphan page limit must be 1..200")
        async with self._index_maintenance_coordinator.operation(
            "obsidian_orphan_census", wait=True
        ):
            state = await self._graph_repository.state()
            notes = tuple(
                ObsidianGraphDiagnosticNote(
                    note_id=node.note_id,
                    relative_path=node.relative_path,
                    title=node.title,
                    project=node.project,
                    tags=(),
                )
                for node in state.projection.nodes
            )
            edges = tuple(
                ObsidianGraphDiagnosticEdge(
                    edge_id=edge.edge_id,
                    source_note_id=edge.source_note_id,
                    target_note_id=edge.target_note_id,
                    relation=edge.relation.value,
                    source_kind=edge.source_kind.value,
                )
                for edge in state.projection.edges
            )
            result = self._compute_provider.compute(
                notes=notes,
                edges=edges,
                orphan_request=ObsidianGraphOrphanDiagnosticRequest(
                    project=project,
                    cursor=cursor,
                    limit=limit,
                ),
                suggestion_request=None,
            )
            entries: list[ObsidianGraphOrphanEntry] = []
            for orphan in result.orphans:
                acknowledgement = await self._checkpoints.load_acknowledgement(
                    orphan.note_id
                )
                metadata = await self._checkpoints.observe_orphan(
                    note_id=orphan.note_id,
                    graph_run_id=state.run_id,
                )
                note = (
                    await index_repository.get_by_id(orphan.note_id)
                    if index_repository is not None
                    else None
                )
                entries.append(
                    ObsidianGraphOrphanEntry(
                        note_id=orphan.note_id,
                        relative_path=orphan.relative_path,
                        title=orphan.title,
                        project=orphan.project,
                        status=(
                            acknowledgement.decision
                            if acknowledgement is not None
                            else "OPEN"
                        ),
                        in_degree=orphan.in_degree,
                        out_degree=orphan.out_degree,
                        canonical_parent_count=orphan.canonical_parent_count,
                        has_wikilink_connectivity=orphan.has_wikilink_connectivity,
                        debt_kinds=orphan.debt_kinds,
                        has_declared_relations=(
                            note is not None and _has_declared_relations(note)
                        ),
                        acknowledgement_reason=(
                            None if acknowledgement is None else acknowledgement.reason
                        ),
                        first_seen_at=metadata.first_seen_at,
                        last_seen_at=metadata.last_seen_at,
                        first_seen_run_id=metadata.first_seen_run_id,
                        last_seen_run_id=metadata.last_seen_run_id,
                        graph_run_id=metadata.graph_run_id,
                    )
                )
            return ObsidianGraphOrphanCensusResult(
                orphans=tuple(entries),
                total_orphans=result.total_orphans,
                next_cursor=result.next_cursor,
            )

    async def get_orphan_status(
        self,
        *,
        note_id: str,
        index_repository: IObsidianIndexRepository | None = None,
    ) -> ObsidianGraphOrphanEntry:
        """Read exact current debt for one note through native diagnosis.

        Args:
            note_id: Stable identifier of the note to diagnose.
            index_repository: Optional session-scoped index reader used to
                inspect declared relation metadata.

        Returns:
            Current orphan diagnostic status and durable census provenance.
        """
        if not note_id.strip():
            raise ObsidianValidationError("orphan note_id is required")
        async with self._index_maintenance_coordinator.operation(
            "obsidian_orphan_status", wait=True
        ):
            state = await self._graph_repository.state()
            if not state.initialized:
                raise ObsidianValidationError(
                    "graph projection is uninitialized; orphan status unavailable"
                )
            projection_nodes = tuple(
                sorted(state.projection.nodes, key=lambda node: node.relative_path)
            )
            target = next(
                (node for node in projection_nodes if node.note_id == note_id),
                None,
            )
            if target is None:
                raise ObsidianNotFoundError(
                    f"graph projection has no current note: {note_id}"
                )
            notes = tuple(
                ObsidianGraphDiagnosticNote(
                    note_id=node.note_id,
                    relative_path=node.relative_path,
                    title=node.title,
                    project=node.project,
                    tags=(),
                )
                for node in projection_nodes
            )
            edges = tuple(
                ObsidianGraphDiagnosticEdge(
                    edge_id=edge.edge_id,
                    source_note_id=edge.source_note_id,
                    target_note_id=edge.target_note_id,
                    relation=edge.relation.value,
                    source_kind=edge.source_kind.value,
                )
                for edge in state.projection.edges
            )
            predecessor = next(
                (
                    node.relative_path
                    for node in reversed(projection_nodes)
                    if node.relative_path < target.relative_path
                ),
                None,
            )
            result = self._compute_provider.compute(
                notes=notes,
                edges=edges,
                orphan_request=ObsidianGraphOrphanDiagnosticRequest(
                    project=target.project,
                    cursor=predecessor,
                    limit=1,
                ),
                suggestion_request=None,
            )
            diagnostic = next(
                (orphan for orphan in result.orphans if orphan.note_id == note_id),
                None,
            )
            acknowledgement = await self._checkpoints.load_acknowledgement(note_id)
            metadata = await self._checkpoints.load_census_metadata(note_id)
            note = (
                await index_repository.get_by_id(note_id)
                if index_repository is not None
                else None
            )
            return ObsidianGraphOrphanEntry(
                note_id=note_id,
                relative_path=target.relative_path,
                title=target.title,
                project=target.project,
                status=(
                    acknowledgement.decision
                    if diagnostic is not None and acknowledgement is not None
                    else "OPEN"
                    if diagnostic is not None
                    else "RESOLVED"
                ),
                in_degree=None if diagnostic is None else diagnostic.in_degree,
                out_degree=None if diagnostic is None else diagnostic.out_degree,
                canonical_parent_count=(
                    None if diagnostic is None else diagnostic.canonical_parent_count
                ),
                has_wikilink_connectivity=(
                    None if diagnostic is None else diagnostic.has_wikilink_connectivity
                ),
                debt_kinds=() if diagnostic is None else diagnostic.debt_kinds,
                has_declared_relations=(
                    None if note is None else _has_declared_relations(note)
                ),
                acknowledgement_reason=(
                    None if acknowledgement is None else acknowledgement.reason
                ),
                first_seen_at=None if metadata is None else metadata.first_seen_at,
                last_seen_at=None if metadata is None else metadata.last_seen_at,
                first_seen_run_id=(
                    None if metadata is None else metadata.first_seen_run_id
                ),
                last_seen_run_id=(
                    None if metadata is None else metadata.last_seen_run_id
                ),
                graph_run_id=state.run_id,
            )

    async def acknowledge_orphan(
        self,
        *,
        note_id: str,
        decision: OrphanDecision,
        reason: str | None = None,
        acknowledged_by: str = "agent",
    ) -> ObsidianOrphanAcknowledgement:
        """Persist one census acknowledgement for a standalone note.

        Args:
            note_id: Orphan note identifier.
            decision: Acknowledged standalone or ignored with reason.
            reason: Required context for IGNORED_WITH_REASON.
            acknowledged_by: Actor label for provenance.

        Returns:
            The persisted acknowledgement record.
        """
        if decision == "IGNORED_WITH_REASON" and not (reason or "").strip():
            raise ObsidianValidationError("IGNORED_WITH_REASON requires a reason")
        async with self._index_maintenance_coordinator.operation(
            "obsidian_orphan_acknowledgement", wait=True
        ):
            existing = await self._checkpoints.load_acknowledgement(note_id)
            if existing is not None:
                if (
                    existing.decision != decision
                    or existing.reason != reason
                    or existing.acknowledged_by != acknowledged_by
                ):
                    raise ObsidianValidationError(
                        "orphan acknowledgement already exists with a different "
                        "decision or provenance"
                    )
                return existing
            acknowledgement = ObsidianOrphanAcknowledgement(
                note_id=note_id,
                decision=decision,
                acknowledged_at=utc_now(),
                acknowledged_by=acknowledged_by,
                reason=reason,
            )
            await self._checkpoints.save_acknowledgement(acknowledgement)
            return acknowledgement

    async def suggest_relations(
        self,
        *,
        note_id: str | None = None,
        path: str | None = None,
        limit: int = 10,
        index_repository: IObsidianIndexRepository | None = None,
    ) -> ObsidianGraphRelationSuggestionsResult:
        """Propose deterministic relation candidates for one seed note.

        Args:
            note_id: Seed note identifier.
            path: Seed note vault-relative path.
            limit: Maximum suggestions (1..50).
            index_repository: Session-scoped index reader; required.

        Returns:
            Evidence-backed suggestions ordered by score then path.
        """
        if not 1 <= limit <= 50:
            raise ObsidianValidationError("suggestion limit must be 1..50")
        if index_repository is None:
            raise ObsidianValidationError(
                "relation suggestions require index metadata access"
            )
        note = (
            await index_repository.get_by_id(note_id)
            if note_id is not None
            else await index_repository.get_by_path(path or "")
        )
        if note is None:
            raise ObsidianNotFoundError(f"Obsidian note not found: {note_id or path}")
        canonical_seed = (
            await self._source_reader.read_note(note.note_id)
            if note_id is not None
            else await self._source_reader.read_note_by_path(note.relative_path)
        )
        if canonical_seed.note_id != note.note_id or (
            path is not None and canonical_seed.relative_path != note.relative_path
        ):
            raise ObsidianValidationError(
                "canonical seed read did not match the requested note identity"
            )
        projection = (await self._graph_repository.state()).projection
        candidates = await index_repository.list_indexed_notes()
        indexed_by_id = {candidate.note_id: candidate for candidate in candidates}
        notes = tuple(
            ObsidianGraphDiagnosticNote(
                note_id=node.note_id,
                relative_path=node.relative_path,
                title=indexed_by_id.get(node.note_id, note).title
                if node.note_id in indexed_by_id
                else node.title,
                project=node.project,
                tags=tuple(indexed_by_id[node.note_id].tags)
                if node.note_id in indexed_by_id
                else (),
            )
            for node in projection.nodes
        )
        edges = tuple(
            ObsidianGraphDiagnosticEdge(
                edge_id=edge.edge_id,
                source_note_id=edge.source_note_id,
                target_note_id=edge.target_note_id,
                relation=edge.relation.value,
                source_kind=edge.source_kind.value,
            )
            for edge in projection.edges
        )
        native_result = self._compute_provider.compute(
            notes=notes,
            edges=edges,
            orphan_request=None,
            suggestion_request=ObsidianGraphSuggestionDiagnosticRequest(
                seed_note_id=canonical_seed.note_id,
                limit=limit,
            ),
        )
        suggestions: list[ObsidianGraphRelationSuggestion] = []
        for suggestion in native_result.suggestions:
            try:
                candidate = await self._source_reader.read_note(
                    suggestion.candidate_note_id
                )
            except ObsidianDomainError, OSError, ValueError:
                continue
            if candidate.relative_path != suggestion.candidate_path:
                continue
            suggestions.append(
                ObsidianGraphRelationSuggestion(
                    candidate_note_id=candidate.note_id,
                    candidate_path=candidate.relative_path,
                    candidate_title=candidate.title,
                    relation=suggestion.relation,
                    confidence=suggestion.confidence,
                    shared_tags=suggestion.shared_tags,
                    shared_neighbor_count=suggestion.shared_neighbor_count,
                    title_overlap_tokens=suggestion.title_overlap_tokens,
                    explanation=suggestion.explanation,
                )
            )
        return ObsidianGraphRelationSuggestionsResult(
            note_id=canonical_seed.note_id,
            relative_path=canonical_seed.relative_path,
            suggestions=tuple(suggestions[:limit]),
        )


def _has_declared_relations(note: ObsidianNote) -> bool:
    """Return whether one note still declares relation frontmatter."""
    return any(key in note.frontmatter for key in _RELATION_FIELD_NAMES)
