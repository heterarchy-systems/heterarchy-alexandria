"""Real PostgreSQL tests for the graph issue list diagnostics service."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.application.graph.diagnostics.obsidian_graph_issue_list_service import (
    ObsidianGraphIssueListService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.contracts.obsidian_graph_issue_contracts import (
    ObsidianGraphIssueListQuery,
    ObsidianGraphIssueListValidationError,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (
    create_native_obsidian_graph_projection_compute_provider,
)
from app.obsidian.infrastructure.graph.sqlalchemy_obsidian_graph_projection_source import (
    SqlAlchemyObsidianGraphProjectionSource,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.infrastructure.database import Database


def _save(title: str, note_id: str, body: str) -> ObsidianSaveNote:
    """Build one context save payload.

    Args:
        title: Note title.
        note_id: Stable note id.
        body: Note body.

    Returns:
        Save payload for the canonical context note.
    """
    return ObsidianSaveNote(
        title=title,
        body=body,
        alexandria_type=AlexandriaNoteType.CONTEXT,
        note_id=note_id,
        relative_path=f"Alexandria/Contexts/{note_id}.md",
        frontmatter={"scope": "GLOBAL"},
    )


def _config(vault_path: Path) -> object:
    """Build a minimal app config for the temporary vault.

    Args:
        vault_path: Temporary vault path.

    Returns:
        App config namespace.
    """
    from app.platform.config.app_config import AppConfig

    return AppConfig(obsidian_vault_path=str(vault_path))


def _issue_services(
    session: AsyncSession,
    repository: SqlAlchemyObsidianIndexRepository,
    vault_path: Path,
) -> tuple[ObsidianGraphIssueListService, ObsidianGraphProjectionRebuildService]:
    """Wire the issue list service with the real compute authority.

    Args:
        session: Active session.
        repository: Index repository.
        vault_path: Temporary vault path.

    Returns:
        Issue list service and projection rebuild service.
    """
    compute = create_native_obsidian_graph_projection_compute_provider()
    source = SqlAlchemyObsidianGraphProjectionSource(session=session)
    rebuild = ObsidianGraphProjectionRebuildService(
        config=_config(vault_path),
        source_builder=ObsidianGraphProjectionSourceBuilder(
            source=source,
            compute_provider=compute,
        ),
        repository=repository,
        index_maintenance_coordinator=IndexMaintenanceCoordinator(),
    )
    service = ObsidianGraphIssueListService(
        source=source,
        compute_provider=compute,
        projection_status=rebuild.status,
    )
    return service, rebuild


def test_graph_issue_list_reports_exact_source_and_target(tmp_path: Path) -> None:
    """A broken wikilink must surface with exact source and target detail."""

    async def scenario() -> tuple[list[str], list[str], list[str], str]:
        database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "issue-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            obsidian = ObsidianService(
                repository=repository,
                vault_path=str(vault_path),
                alexandria_root="Alexandria",
            )
            await obsidian.save_note(
                _save("Hub Note", "ctx_issue_hub", "Hub body with no links.")
            )
            await obsidian.save_note(
                _save(
                    "Broken Source",
                    "ctx_issue_source",
                    "See [[ctx_issue_missing]] for details.",
                )
            )
            service, rebuild = _issue_services(session, repository, vault_path)
            await rebuild.rebuild()
            result = await service.list_issues(
                ObsidianGraphIssueListQuery(code="missing_target_note", limit=50)
            )
            codes = [issue.code for issue in result.issues]
            sources = [issue.source_note_id for issue in result.issues]
            targets = [issue.target_path for issue in result.issues]
            issue_ids = [issue.issue_id for issue in result.issues]
        finally:
            await session.close()
            await database.shutdown()
        return codes, sources, targets, issue_ids[0] if issue_ids else ""

    codes, sources, targets, first_issue_id = anyio.run(scenario)
    assert codes == ["missing_target_note"]
    assert sources == ["ctx_issue_source"]
    assert targets == ["Alexandria/ctx_issue_missing.md"]
    assert len(first_issue_id) == 64


def test_graph_issue_list_filters_and_paginates(tmp_path: Path) -> None:
    """Code filters and keyset cursor must bound the returned page."""

    async def scenario() -> tuple[int, str | None, str]:
        database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "filter-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            obsidian = ObsidianService(
                repository=repository,
                vault_path=str(vault_path),
                alexandria_root="Alexandria",
            )
            await obsidian.save_note(
                _save("Filter Source", "ctx_filter_source", "See [[ctx_absent]].")
            )
            await obsidian.save_note(_save("Quiet", "ctx_quiet", "No links here."))
            service, rebuild = _issue_services(session, repository, vault_path)
            await rebuild.rebuild()
            filtered = await service.list_issues(
                ObsidianGraphIssueListQuery(code="ambiguous_target_note", limit=50)
            )
            page = await service.list_issues(
                ObsidianGraphIssueListQuery(code="missing_target_note", limit=50)
            )
            invalid = "not-raised"
            try:
                await service.list_issues(ObsidianGraphIssueListQuery(limit=0))
            except ObsidianGraphIssueListValidationError:
                invalid = "raised"
            return (
                len(filtered.issues),
                page.next_cursor,
                invalid,
            )
        finally:
            await session.close()
            await database.shutdown()

    filtered_count, next_cursor, invalid = anyio.run(scenario)
    assert filtered_count == 0
    assert next_cursor is None
    assert invalid == "raised"


def test_graph_issue_query_rejects_invalid_limit() -> None:
    """Out-of-bounds limits must be rejected before any compute."""
    with pytest.raises(ObsidianGraphIssueListValidationError):
        ObsidianGraphIssueListQuery(limit=0)
    with pytest.raises(ObsidianGraphIssueListValidationError):
        ObsidianGraphIssueListQuery(limit=201)
