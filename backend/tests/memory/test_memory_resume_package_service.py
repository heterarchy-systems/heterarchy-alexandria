"""Resume context package service behavior tests."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import anyio
import pytest

from app.memory.application.contexts.linting.context_lint import (
    ContextLintInput,
    lint_context,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageAttributedItem,
    ResumePackageDraft,
    ResumePackageLineage,
)
from app.memory.application.memory_compacts.resume_package.resume_package_service import (
    MemoryResumePackageService,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryResumePackageEvidenceNotFoundError,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextNotFoundError

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
COVERED_FROM = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
COVERED_TO = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
PROJECT = "heterarchy-alexandria"


class _StaticEvidenceSource:
    """In-memory structural evidence seam standing in for ContextService."""

    def __init__(self, records: dict[str, ContextRecord]) -> None:
        self._records = records

    async def get(self, context_id: str) -> ContextRecord:
        """Return one stored record or raise the typed not-found error.

        Args:
            context_id: Stored Context identifier.

        Returns:
            Stored Context read model.
        """
        record = self._records.get(context_id)
        if record is None:
            raise MemoryContextNotFoundError(f"Context not found: {context_id}")
        return record


def _context_record(context_id: str, content: str) -> ContextRecord:
    """Build one stored Context record for evidence.

    Args:
        context_id: Stored Context identifier.
        content: Observed Context content.

    Returns:
        Context read model with deterministic observed fields.
    """
    return ContextRecord(
        id=context_id,
        kind=ContextKind.HANDOFF,
        title=f"Context {context_id}",
        summary="summary",
        content=content,
        content_format=ContextContentFormat.MARKDOWN,
        project=PROJECT,
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="Hermes",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.HIGH,
        tags=["memory"],
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata=ContextMetadataPayload(),
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


def _compact_service(vault_path: Path) -> MemoryCompactService:
    """Build a Memory Compact facade over one tmp_path vault.

    Args:
        vault_path: Obsidian vault root path.

    Returns:
        Memory Compact application facade.
    """
    return MemoryCompactService(
        repository=ObsidianMemoryCompactRepository(
            vault_path=vault_path,
            relative_dir="Alexandria/Memory Compacts",
        )
    )


def _service(
    vault_path: Path,
    records: dict[str, ContextRecord],
) -> MemoryResumePackageService:
    """Build the resume package service over a tmp_path vault.

    Args:
        vault_path: Obsidian vault root path.
        records: Stored evidence records for the evidence seam.

    Returns:
        Resume package service over the compact path.
    """
    return MemoryResumePackageService(
        compact_service=_compact_service(vault_path),
        evidence_source=_StaticEvidenceSource(records),
    )


def _records() -> dict[str, ContextRecord]:
    """Build the shared evidence records.

    Returns:
        Evidence records keyed by Context id.
    """
    return {
        "ctx-goal": _context_record("ctx-goal", "Goal evidence content"),
        "ctx-change": _context_record("ctx-change", "Change evidence content"),
        "ctx-risk": _context_record("ctx-risk", "Risk evidence content"),
    }


def _draft(
    *,
    summary: str = "Sealed worker handoff for the overnight plan",
    next_single_action: str = "Run the resume package verification gates",
    evidence_context_ids: tuple[str, ...] = (
        "ctx-goal",
        "ctx-change",
        "ctx-risk",
    ),
) -> ResumePackageDraft:
    """Build one deterministic resume package draft.

    Args:
        summary: Package summary override.
        next_single_action: Next single action override.
        evidence_context_ids: Evidence Context id override.

    Returns:
        Resume package draft.
    """
    return ResumePackageDraft(
        project=PROJECT,
        goal="Ship the versioned resume context package",
        summary=summary,
        current_state="Resume package machinery is implemented on the compact path",
        next_single_action=next_single_action,
        covered_from=COVERED_FROM,
        covered_to=COVERED_TO,
        lineage=ResumePackageLineage(
            lineage_id="lineage-1",
            worker_id="worker-7",
            run_id="run-9",
        ),
        evidence_context_ids=evidence_context_ids,
        accepted_changes=(
            ResumePackageAttributedItem(
                text="Resume packages seal through the compact creation path",
                source_context_id="ctx-change",
            ),
        ),
        constraints=(
            ResumePackageAttributedItem(
                text="Packages stay data only without execution authority",
                source_context_id="ctx-risk",
            ),
        ),
        verified_complete=("Round-trip storage through the note store",),
        implemented_unverified=("Cross-process revision race handling",),
        unfinished_tasks=("Consumer adoption by the next worker",),
        uncertain_results=("Rubric thresholds for very large packages",),
        blockers=("No active blockers",),
    )


def test_resume_package_round_trip_preserves_goal_evidence_and_unverified_state(
    tmp_path: Path,
) -> None:
    """Create then reopen must preserve ids, sources, and unverified state."""

    async def scenario() -> None:
        service = _service(tmp_path / "vault", _records())
        seal = await service.create_resume_package(_draft())
        view = await service.get_resume_package(seal.package_id)

        assert view.package_id == seal.package_id
        assert view.status is MemoryCompactStatus.CURRENT
        assert view.project == PROJECT
        assert view.goal == "Ship the versioned resume context package"
        assert view.summary == "Sealed worker handoff for the overnight plan"
        assert (
            view.current_state
            == "Resume package machinery is implemented on the compact path"
        )
        assert view.next_single_action == "Run the resume package verification gates"
        assert view.accepted_changes == (
            ResumePackageAttributedItem(
                text="Resume packages seal through the compact creation path",
                source_context_id="ctx-change",
            ),
        )
        assert view.constraints == (
            ResumePackageAttributedItem(
                text="Packages stay data only without execution authority",
                source_context_id="ctx-risk",
            ),
        )
        assert view.verified_complete == ("Round-trip storage through the note store",)
        assert view.implemented_unverified == ("Cross-process revision race handling",)
        assert view.unfinished_tasks == ("Consumer adoption by the next worker",)
        assert view.uncertain_results == ("Rubric thresholds for very large packages",)
        assert view.blockers == ("No active blockers",)
        assert view.lineage == ResumePackageLineage(
            lineage_id="lineage-1",
            worker_id="worker-7",
            run_id="run-9",
            previous_package_id=None,
            package_revision=1,
        )
        assert view.draft_hash == seal.draft_hash
        assert [
            (ref.context_id, ref.content_hash, ref.source) for ref in view.evidence_refs
        ] == [
            ("ctx-goal", sha256(b"Goal evidence content").hexdigest(), "AGENT:Hermes"),
            (
                "ctx-change",
                sha256(b"Change evidence content").hexdigest(),
                "AGENT:Hermes",
            ),
            ("ctx-risk", sha256(b"Risk evidence content").hexdigest(), "AGENT:Hermes"),
        ]
        assert all(ref.created_at == NOW for ref in view.evidence_refs)
        assert all(ref.observed_updated_at == NOW for ref in view.evidence_refs)
        assert seal.package_revision == 1
        assert seal.previous_package_id is None
        assert seal.deduplicated is False
        assert seal.compaction_policy_version == "memory-compact-v2"
        assert seal.source_set_hash is not None

    anyio.run(scenario)


def test_resume_package_revision_increments_and_supersedes_previous_for_same_lineage(
    tmp_path: Path,
) -> None:
    """Second package on a lineage increments revision and moves the pointer."""

    async def scenario() -> None:
        vault = tmp_path / "vault"
        service = _service(vault, _records())
        first = await service.create_resume_package(_draft())
        second = await service.create_resume_package(
            _draft(
                next_single_action="Resume from the second sealed revision",
                summary="Sealed worker handoff after revision one",
            )
        )
        previous = await service.get_resume_package(first.package_id)
        current = await service.get_resume_package(second.package_id)
        compact_current = await _compact_service(vault).current(project=PROJECT)
        listed, total = await _compact_service(vault).list_compacts(project=PROJECT)

        assert first.package_revision == 1
        assert second.package_revision == 2
        assert second.previous_package_id == first.package_id
        assert previous.lineage.package_revision == 1
        assert previous.status is MemoryCompactStatus.SUPERSEDED
        assert current.status is MemoryCompactStatus.CURRENT
        assert compact_current is not None
        assert compact_current.id == second.package_id
        assert total == 2
        assert {item.id for item in listed} == {
            first.package_id,
            second.package_id,
        }

    anyio.run(scenario)


def test_resume_package_identical_draft_is_deduplicated_without_new_store_entry(
    tmp_path: Path,
) -> None:
    """Identical content and evidence must reuse the stored package identity."""

    async def scenario() -> tuple[int, int, int]:
        vault = tmp_path / "vault"
        service = _service(vault, _records())
        first = await service.create_resume_package(_draft())
        duplicate = await service.create_resume_package(_draft())
        listed, total = await _compact_service(vault).list_compacts(project=PROJECT)
        note_paths = list((vault / "Alexandria" / "Memory Compacts").rglob("*.md"))

        assert duplicate.package_id == first.package_id
        assert duplicate.package_revision == first.package_revision
        assert duplicate.draft_hash == first.draft_hash
        assert duplicate.previous_package_id == first.previous_package_id
        assert duplicate.deduplicated is True
        assert first.deduplicated is False
        return total, len(note_paths), len(listed)

    total, note_count, listed_count = anyio.run(scenario)

    assert total == 1
    assert note_count == 1
    assert listed_count == 1


def test_resume_package_missing_evidence_ref_raises_and_persists_nothing(
    tmp_path: Path,
) -> None:
    """A missing evidence Context must fail closed before any write."""

    async def scenario() -> tuple[int, int]:
        vault = tmp_path / "vault"
        service = _service(vault, _records())
        with pytest.raises(
            MemoryResumePackageEvidenceNotFoundError,
            match="ctx-missing",
        ):
            await service.create_resume_package(
                _draft(evidence_context_ids=("ctx-goal", "ctx-missing"))
            )
        _listed, total = await _compact_service(vault).list_compacts(project=PROJECT)
        note_paths = list((vault / "Alexandria" / "Memory Compacts").rglob("*.md"))
        return total, len(note_paths)

    total, note_count = anyio.run(scenario)

    assert total == 0
    assert note_count == 0


def test_resume_package_body_passes_handoff_lint_contract(tmp_path: Path) -> None:
    """The sealed body must pass the existing HANDOFF lint unmodified."""

    async def scenario() -> None:
        service = _service(tmp_path / "vault", _records())
        seal = await service.create_resume_package(_draft())
        lint = lint_context(
            ContextLintInput(
                kind=ContextKind.HANDOFF,
                title="Resume package",
                content=seal.markdown_body,
                summary=seal.markdown_body.splitlines()[1],
                project=PROJECT,
            )
        )

        assert lint.ok is True
        assert lint.errors == ()
        assert not any("missing heading" in warning for warning in lint.warnings)

    anyio.run(scenario)
