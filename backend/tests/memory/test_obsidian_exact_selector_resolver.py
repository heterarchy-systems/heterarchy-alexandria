"""Focused source-read evidence for exact high-level recall selectors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio

from app.memory.application.retrieval.obsidian_exact_selector_resolver import (
    ObsidianExactSelectorResolver,
)
from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.contracts.recall_contracts import RecallExactSelector
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import ContextScope
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianCanonicalIdentityResult,
    ObsidianExactPathStatus,
    ObsidianNote,
    ObsidianVaultLocation,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class _ObsidianFake:
    """Source facade fake that exposes only the exact-read methods used here."""

    def __init__(self, note: ObsidianNote) -> None:
        self.note = note
        self.read_ids: list[str] = []
        self.read_paths: list[str] = []

    async def read_note(self, note_id: str) -> ObsidianNote:
        self.read_ids.append(note_id)
        return self.note

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        self.read_paths.append(relative_path)
        return self.note

    def vault_location(self) -> ObsidianVaultLocation:
        return ObsidianVaultLocation(
            vault_path="/tmp/test-vault",
            alexandria_root="Alexandria",
        )


class _IdentityFake:
    """Canonical identity fake used to prove path and logical selector routing."""

    def __init__(self, note: ObsidianNote) -> None:
        self.note = note

    async def check_path(self, path: str) -> ObsidianExactPathStatus:
        return ObsidianExactPathStatus(
            exists=True,
            relative_path=path,
            note_id=self.note.note_id,
            index_status=self.note.index_status,
        )

    async def resolve_logical_identity(
        self,
        identity: ObsidianLogicalIdentity,
    ) -> ObsidianCanonicalIdentityResult:
        return ObsidianCanonicalIdentityResult(
            canonical_report_family=identity.report,
            canonical_entity=identity.entity,
            canonical_path=self.note.relative_path,
            existing_note_id=self.note.note_id,
            aliases=(),
            resolution="EXISTING_CANONICAL_FAMILY",
        )


def _note() -> ObsidianNote:
    return ObsidianNote(
        note_id="source-note",
        relative_path="Alexandria/Contexts/Source.md",
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        title="Source note",
        status="active",
        tags=(),
        project="alexandria",
        source="test",
        content_hash="content-hash",
        frontmatter={
            "id": "source-note",
            "title": "Source note",
            "status": "active",
            "project": "alexandria",
        },
        body="# Source note\n\nCanonical body.",
        index_status=ObsidianIndexStatus.UNINDEXED,
        error_message="INDEX_METADATA_UNAVAILABLE",
        size_bytes=32,
        modified_at=NOW,
        indexed_at=None,
    )


def _resolver(
    note: ObsidianNote,
) -> tuple[ObsidianExactSelectorResolver, _ObsidianFake]:
    source = _ObsidianFake(note)
    resolver = ObsidianExactSelectorResolver(
        cast(ObsidianService, source),
        cast(ObsidianCanonicalIdentityService, _IdentityFake(note)),
    )
    return resolver, source


def _scope() -> ScopeIdentity:
    return ScopeIdentity(
        include_scopes=(ContextScope.PROJECT, ContextScope.GLOBAL),
        project="alexandria",
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
    )


def test_exact_path_preserves_unindexed_projection_truth() -> None:
    note = _note()
    resolver, source = _resolver(note)

    async def scenario() -> tuple[ContextSearchMatch, ...]:
        return await resolver.resolve(
            RecallExactSelector(path=note.relative_path), _scope()
        )

    matches = anyio.run(scenario)
    assert len(matches) == 1
    assert matches[0].context.context_metadata["index_status"] == "unindexed"
    assert matches[0].context.updated_at == note.modified_at
    assert matches[0].context.updated_at != note.indexed_at
    assert source.read_paths == [note.relative_path]


def test_exact_logical_identity_uses_canonical_identity_service() -> None:
    note = _note()
    resolver, source = _resolver(note)
    identity = ObsidianLogicalIdentity(
        project="alexandria",
        report="implementation",
        date="2026-09-08",
        entity="recall",
    )

    async def scenario() -> tuple[ContextSearchMatch, ...]:
        return await resolver.resolve(
            RecallExactSelector(logical_identity=identity),
            _scope(),
        )

    matches = anyio.run(scenario)
    assert len(matches) == 1
    assert source.read_ids == [note.note_id]
