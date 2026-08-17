"""Memory Compact service behavior tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from app.memory.application.memory_compact_review_contracts import (
    MemoryCompactSourceObservation,
)
from app.memory.application.memory_compact_service import MemoryCompactService
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.domain.repositories.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactValidationError


def _service(vault_path: Path) -> MemoryCompactService:
    return MemoryCompactService(
        repository=ObsidianMemoryCompactRepository(
            vault_path=vault_path,
            relative_dir="Alexandria/Memory Compacts",
        )
    )


def _compact_note_path(vault_path: Path, compact_id: str) -> Path:
    notes_dir = vault_path / "Alexandria" / "Memory Compacts"
    matches = list(notes_dir.rglob(f"{compact_id}.md"))
    assert len(matches) == 1
    return matches[0]


def _source_ref(
    source_id: str = "ctx-1",
    *,
    source_hash: str | None = None,
) -> MemoryCompactSourceRefCreate:
    return MemoryCompactSourceRefCreate(
        source_type="CONTEXT",
        source_id=source_id,
        title="Context source",
        detail_path=f"/memory/contexts/{source_id}",
        source_hash=source_hash,
    )


def _compact_body(
    *,
    covered_from: datetime = datetime(2026, 5, 1, tzinfo=UTC),
    covered_to: datetime = datetime(2026, 5, 10, tzinfo=UTC),
    project: str = "heterarchy-alexandria",
) -> str:
    return f"""## Durable Decisions
- Keep this compact as the current project summary.

## Current State
- Durable summary is current, scoped, and ready for follow-up work.

## Risks and Blockers
- No active blockers; validation risk is tracked through source refs.

## Next Actions
- Continue from this compact.

## Coverage
- covered_from: {covered_from.isoformat()}
- covered_to: {covered_to.isoformat()}
- project: {project}

## Evidence Summary
- Context source supports the compact claims.
"""


def _create(status: MemoryCompactStatus) -> MemoryCompactCreate:
    return MemoryCompactCreate(
        project="heterarchy-alexandria",
        covered_from=datetime(2026, 5, 1, tzinfo=UTC),
        covered_to=datetime(2026, 5, 10, tzinfo=UTC),
        markdown_body=_compact_body(),
        status=status,
        source_refs=[_source_ref()],
    )


def test_memory_compact_service_writes_obsidian_note_when_created(
    tmp_path: Path,
) -> None:
    """Memory Compact creation should persist a frontmatter Markdown note."""

    async def scenario() -> None:
        service = _service(tmp_path / "vault")
        compact = await service.create(_create(MemoryCompactStatus.CURRENT))
        note_path = _compact_note_path(tmp_path / "vault", compact.id)
        note = note_path.read_text(encoding="utf-8")

        assert note_path.exists()
        assert "alexandria_type: 'memory_compact'" in note
        assert f"id: '{compact.id}'" in note
        assert "status: 'CURRENT'" in note
        assert "source_refs:" in note
        assert "tags:\n  - 'alexandria'\n  - 'memory-compact'" in note
        assert "review_verdict: 'pass'" in note
        assert "review_score:" in note
        loaded = await service.get(compact.id)
        assert loaded.review_verdict is MemoryCompactReviewVerdict.PASS
        assert loaded.review_score is not None
        assert loaded.review_max_score == 20
        assert loaded.reviewed_at is not None
        assert "## Durable Decisions" in note
        assert "## Evidence Summary" in note

    anyio.run(scenario)


def test_memory_compact_writes_obsidian_property_links_for_note_sources(
    tmp_path: Path,
) -> None:
    """Structured refs stay lossless while Obsidian receives a flat link list."""

    async def scenario() -> str:
        service = _service(tmp_path / "vault")
        payload = _create(MemoryCompactStatus.CURRENT)
        payload = MemoryCompactCreate(
            project=payload.project,
            covered_from=payload.covered_from,
            covered_to=payload.covered_to,
            markdown_body=payload.markdown_body,
            status=payload.status,
            source_refs=[
                MemoryCompactSourceRefCreate(
                    source_type="obsidian_note",
                    source_id="ctx-source",
                    title="Source",
                    detail_path="Alexandria/Contexts/Source.md",
                )
            ],
        )
        compact = await service.create(payload)
        return _compact_note_path(tmp_path / "vault", compact.id).read_text(
            encoding="utf-8"
        )

    note = anyio.run(scenario)

    assert "source_ref_links:\n  - '[[Alexandria/Contexts/Source]]'" in note
    assert '"source_id":"ctx-source"' in note


def test_memory_compact_service_supersedes_previous_current_when_new_current_created(
    tmp_path: Path,
) -> None:
    """Project should have one CURRENT compact and supersede prior notes."""

    async def scenario() -> None:
        service = _service(tmp_path / "vault")
        first = await service.create(_create(MemoryCompactStatus.CURRENT))
        second_payload = _create(MemoryCompactStatus.CURRENT)
        second = await service.create(
            MemoryCompactCreate(
                project=second_payload.project,
                covered_from=datetime(2026, 5, 11, tzinfo=UTC),
                covered_to=datetime(2026, 5, 15, tzinfo=UTC),
                markdown_body=_compact_body(
                    covered_from=datetime(2026, 5, 11, tzinfo=UTC),
                    covered_to=datetime(2026, 5, 15, tzinfo=UTC),
                ),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[_source_ref("ctx-2")],
            )
        )
        current = await service.current(project="heterarchy-alexandria")
        previous = await service.get(first.id)
        listed, total = await service.list_compacts(project="heterarchy-alexandria")

        assert total == 2
        assert current.id == second.id
        assert previous.status is MemoryCompactStatus.SUPERSEDED
        assert [item.id for item in listed] == [second.id, first.id]

    anyio.run(scenario)


def test_memory_compact_current_supersede_is_isolated_by_project(
    tmp_path: Path,
) -> None:
    """New CURRENT compacts should supersede only the matching project."""

    async def scenario() -> tuple[str, str, str, str, str, str, str]:
        service = _service(tmp_path / "vault")
        project_a_first = await service.create(_create(MemoryCompactStatus.CURRENT))
        project_b = await service.create(
            MemoryCompactCreate(
                project="other-project",
                covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                markdown_body=_compact_body(project="other-project"),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[_source_ref("ctx-project-b")],
            )
        )
        default_project = await service.create(
            MemoryCompactCreate(
                project=None,
                covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                markdown_body=_compact_body(project="default"),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[_source_ref("ctx-default")],
            )
        )
        await service.create(
            MemoryCompactCreate(
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 5, 11, tzinfo=UTC),
                covered_to=datetime(2026, 5, 15, tzinfo=UTC),
                markdown_body=_compact_body(
                    covered_from=datetime(2026, 5, 11, tzinfo=UTC),
                    covered_to=datetime(2026, 5, 15, tzinfo=UTC),
                ),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[_source_ref("ctx-project-a-2")],
            )
        )

        loaded_a_first = await service.get(project_a_first.id)
        loaded_project_b = await service.get(project_b.id)
        loaded_default = await service.get(default_project.id)
        current_b = await service.current(project="other-project")
        current_default = await service.current(project=None)

        return (
            loaded_a_first.status.value,
            loaded_project_b.status.value,
            loaded_default.status.value,
            project_b.id,
            current_b.id,
            default_project.id,
            current_default.id,
        )

    (
        a_status,
        b_status,
        default_status,
        project_b_id,
        current_b_id,
        default_id,
        current_default_id,
    ) = anyio.run(scenario)

    assert a_status == "SUPERSEDED"
    assert b_status == "CURRENT"
    assert default_status == "CURRENT"
    assert current_b_id == project_b_id
    assert current_default_id == default_id


def test_memory_compact_service_reuses_existing_compact_for_same_signature(
    tmp_path: Path,
) -> None:
    """Duplicate Memory Compact signatures should return the existing id."""

    async def scenario() -> tuple[str, str, int, int, str]:
        service = _service(tmp_path / "vault")
        payload = MemoryCompactCreate(
            project="heterarchy-alexandria",
            covered_from=datetime(2026, 5, 1, tzinfo=UTC),
            covered_to=datetime(2026, 5, 10, tzinfo=UTC),
            markdown_body=_compact_body(),
            status=MemoryCompactStatus.CURRENT,
            source_refs=[_source_ref("ctx-b"), _source_ref("ctx-a")],
        )
        first = await service.create(payload)
        duplicate = await service.create(
            MemoryCompactCreate(
                project=payload.project,
                covered_from=payload.covered_from,
                covered_to=payload.covered_to,
                markdown_body=payload.markdown_body,
                status=payload.status,
                source_refs=[_source_ref("ctx-a"), _source_ref("ctx-b")],
            )
        )
        _listed, total = await service.list_compacts(project="heterarchy-alexandria")
        current = await service.current(project="heterarchy-alexandria")
        note_paths = list(
            (tmp_path / "vault" / "Alexandria" / "Memory Compacts").rglob("*.md")
        )

        return first.id, duplicate.id, total, len(note_paths), current.id

    first_id, duplicate_id, total, note_count, current_id = anyio.run(scenario)

    assert duplicate_id == first_id
    assert current_id == first_id
    assert total == 1
    assert note_count == 1


def test_memory_compact_service_rejects_blank_source_ref_fields(
    tmp_path: Path,
) -> None:
    """Source refs should be complete even outside the HTTP schema boundary."""

    async def scenario() -> None:
        service = _service(tmp_path / "vault")
        with pytest.raises(MemoryCompactValidationError, match="source ref"):
            await service.create(
                MemoryCompactCreate(
                    project="heterarchy-alexandria",
                    covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                    covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                    markdown_body=_compact_body(),
                    status=MemoryCompactStatus.CURRENT,
                    source_refs=[
                        MemoryCompactSourceRefCreate(
                            source_type="CONTEXT",
                            source_id=" ",
                            title="Context source",
                            detail_path="/memory/contexts/ctx-1",
                        )
                    ],
                )
            )

    anyio.run(scenario)


def test_memory_compact_service_deduplicates_source_refs_by_stable_key(
    tmp_path: Path,
) -> None:
    """Duplicate source refs should be collapsed before durable persistence."""

    async def scenario() -> tuple[int, list[str]]:
        service = _service(tmp_path / "vault")
        duplicate_a = _source_ref("ctx-duplicate")
        duplicate_b = MemoryCompactSourceRefCreate(
            source_type=duplicate_a.source_type,
            source_id=duplicate_a.source_id,
            title="Same source with alternate title",
            detail_path=duplicate_a.detail_path,
        )
        unique = _source_ref("ctx-unique")

        compact = await service.create(
            MemoryCompactCreate(
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                markdown_body=_compact_body(),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[duplicate_a, duplicate_b, unique, duplicate_a],
            )
        )
        loaded = await service.get(compact.id)

        return len(loaded.source_refs), [ref.title for ref in loaded.source_refs]

    total_refs, titles = anyio.run(scenario)

    assert total_refs == 2
    assert titles == ["Context source", "Context source"]


def test_memory_compact_service_preserves_source_hash_evidence(
    tmp_path: Path,
) -> None:
    """Source refs should keep content hashes for semantic stale detection."""

    async def scenario() -> tuple[str | None, str]:
        service = _service(tmp_path / "vault")
        compact = await service.create(
            MemoryCompactCreate(
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                markdown_body=_compact_body(),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[_source_ref("ctx-hash", source_hash="hash-before")],
            )
        )
        loaded = await service.get(compact.id)
        note = _compact_note_path(tmp_path / "vault", compact.id).read_text(
            encoding="utf-8"
        )

        assert loaded is not None
        return loaded.source_refs[0].source_hash, note

    source_hash, note = anyio.run(scenario)

    assert source_hash == "hash-before"
    assert '"source_hash":"hash-before"' in note


def test_memory_compact_service_review_returns_passing_rubric(
    tmp_path: Path,
) -> None:
    """Librarian review should return scores, pass verdict, and next action."""

    async def scenario() -> tuple[MemoryCompactReviewVerdict, int, list[str], int]:
        service = _service(tmp_path / "vault")
        compact = await service.create(_create(MemoryCompactStatus.CURRENT))
        review = await service.review(compact.id)
        required_zero_count = sum(
            1 for score in review.scores if score.required and score.score == 0
        )

        return (
            review.verdict,
            review.total_score,
            list(review.recommended_actions),
            required_zero_count,
        )

    verdict, total_score, recommended_actions, required_zero_count = anyio.run(scenario)

    assert verdict is MemoryCompactReviewVerdict.PASS
    assert total_score >= 17
    assert recommended_actions == ["promote_or_keep_current"]
    assert required_zero_count == 0


def test_memory_compact_service_review_blocks_stale_source_hash(
    tmp_path: Path,
) -> None:
    """Review should block when observed source evidence changed."""

    async def scenario() -> tuple[MemoryCompactReviewVerdict, list[str], list[str]]:
        service = _service(tmp_path / "vault")
        compact = await service.create(
            MemoryCompactCreate(
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                markdown_body=_compact_body(),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[_source_ref("ctx-hash", source_hash="hash-before")],
            )
        )
        review = await service.review(
            compact.id,
            source_observations=(
                MemoryCompactSourceObservation(
                    source_id="ctx-hash",
                    detail_path="/memory/contexts/ctx-hash",
                    current_source_hash="hash-after",
                ),
            ),
        )

        return (
            review.verdict,
            list(review.stale_reasons),
            list(review.recommended_actions),
        )

    verdict, stale_reasons, recommended_actions = anyio.run(scenario)

    assert verdict is MemoryCompactReviewVerdict.BLOCKED
    assert stale_reasons == ["source_hash_mismatch:ctx-hash"]
    assert recommended_actions == ["refresh_source_evidence"]


def test_memory_compact_service_create_current_requires_evidence_summary_ref_link(
    tmp_path: Path,
) -> None:
    """CURRENT evidence summary should name the source ref supporting claims."""

    async def scenario() -> str:
        service = _service(tmp_path / "vault")
        body = _compact_body().replace(
            "- Context source supports the compact claims.",
            "- External notes support this compact.",
        )
        with pytest.raises(MemoryCompactValidationError) as exc_info:
            await service.create(
                MemoryCompactCreate(
                    project="heterarchy-alexandria",
                    covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                    covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                    markdown_body=body,
                    status=MemoryCompactStatus.CURRENT,
                    source_refs=[_source_ref("ctx-evidence-link")],
                )
            )
        return str(exc_info.value)

    error_message = anyio.run(scenario)

    assert error_message == (
        "Current memory compact review failed: "
        "needs_revision: improve_evidence_completeness"
    )


def test_memory_compact_service_create_current_requires_passing_review(
    tmp_path: Path,
) -> None:
    """CURRENT creation should fail closed when the review rubric is blocked."""

    async def scenario() -> str:
        service = _service(tmp_path / "vault")
        with pytest.raises(MemoryCompactValidationError) as exc_info:
            await service.create(
                MemoryCompactCreate(
                    project="heterarchy-alexandria",
                    covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                    covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                    markdown_body=_compact_body(),
                    status=MemoryCompactStatus.CURRENT,
                    source_refs=[
                        MemoryCompactSourceRefCreate(
                            source_type="CONTEXT",
                            source_id="ctx-broken",
                            title="Broken context source",
                            detail_path="broken:/memory/contexts/ctx-broken",
                        )
                    ],
                )
            )
        return str(exc_info.value)

    error_message = anyio.run(scenario)

    assert error_message == (
        "Current memory compact review failed: blocked: source_ref_broken:ctx-broken"
    )


def test_memory_compact_service_mark_current_requires_passing_review(
    tmp_path: Path,
) -> None:
    """Promotion should fail closed when review finds broken required refs."""

    async def scenario() -> tuple[str, MemoryCompactStatus]:
        service = _service(tmp_path / "vault")
        draft = await service.create(
            MemoryCompactCreate(
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                markdown_body=_compact_body(),
                status=MemoryCompactStatus.DRAFT,
                source_refs=[
                    MemoryCompactSourceRefCreate(
                        source_type="CONTEXT",
                        source_id="ctx-broken",
                        title="Broken context source",
                        detail_path="broken:/memory/contexts/ctx-broken",
                    )
                ],
            )
        )
        with pytest.raises(MemoryCompactValidationError) as exc_info:
            await service.mark_current(draft.id)
        loaded = await service.get(draft.id)
        return str(exc_info.value), loaded.status

    error_message, loaded_status = anyio.run(scenario)

    assert error_message == (
        "Current memory compact review failed: blocked: source_ref_broken:ctx-broken"
    )
    assert loaded_status is MemoryCompactStatus.DRAFT


def test_current_memory_compact_requires_quality_sections(tmp_path: Path) -> None:
    """CURRENT compacts should include the PRD-required body sections."""

    async def scenario() -> str:
        service = _service(tmp_path / "vault")
        with pytest.raises(MemoryCompactValidationError) as exc_info:
            await service.create(
                MemoryCompactCreate(
                    project="heterarchy-alexandria",
                    covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                    covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                    markdown_body="## Current State\n- Too thin.",
                    status=MemoryCompactStatus.CURRENT,
                    source_refs=[_source_ref()],
                )
            )
        return str(exc_info.value)

    error_message = anyio.run(scenario)

    assert error_message == (
        "Current memory compact missing required sections: "
        "Durable Decisions, Risks and Blockers, Next Actions, Coverage, "
        "Evidence Summary"
    )


def test_current_memory_compact_requires_source_refs(tmp_path: Path) -> None:
    """Current compacts should not be accepted without source refs."""

    async def scenario() -> None:
        service = _service(tmp_path / "vault")
        with pytest.raises(MemoryCompactValidationError, match="source refs"):
            await service.create(
                MemoryCompactCreate(
                    project="heterarchy-alexandria",
                    covered_from=datetime(2026, 5, 1, tzinfo=UTC),
                    covered_to=datetime(2026, 5, 10, tzinfo=UTC),
                    markdown_body=_compact_body(),
                    status=MemoryCompactStatus.CURRENT,
                    source_refs=[],
                )
            )

    anyio.run(scenario)


def test_memory_compact_service_lists_legacy_obsidian_notes(
    tmp_path: Path,
) -> None:
    """Legacy Obsidian Memory Compact notes should stay visible to the API."""

    async def scenario() -> None:
        vault = tmp_path / "vault"
        notes_dir = vault / "Alexandria" / "Memory Compacts" / "2026" / "05"
        notes_dir.mkdir(parents=True)
        (notes_dir / "legacy compact.md").write_text(
            """---
alexandria_type: memory_compact
title: Legacy Compact
id: legacy-compact
project: heterarchy-alexandria
status: current
created: 2026-05-28
tags:
  - memory-compact
---
# Legacy Compact

Durable legacy summary.
""",
            encoding="utf-8",
        )

        service = _service(vault)
        current = await service.current(project="heterarchy-alexandria")
        listed, total = await service.list_compacts(project="heterarchy-alexandria")

        assert total == 1
        assert listed == [current]
        assert current.id == "legacy-compact"
        assert current.status is MemoryCompactStatus.CURRENT
        assert current.markdown_body == "# Legacy Compact\n\nDurable legacy summary."
        assert current.covered_from == datetime(2026, 5, 28, tzinfo=UTC)
        assert current.covered_to == datetime(2026, 5, 28, tzinfo=UTC)

    anyio.run(scenario)


def test_memory_compact_service_deduplicates_same_id_lifecycle_notes(
    tmp_path: Path,
) -> None:
    """Compact list/get should expose one lifecycle state per durable compact id."""

    async def scenario() -> tuple[int, list[tuple[str, MemoryCompactStatus]], str]:
        vault = tmp_path / "vault"
        notes_dir = vault / "Alexandria" / "Memory Compacts" / "2026" / "07"
        notes_dir.mkdir(parents=True)
        (notes_dir / "old-current-copy.md").write_text(
            """---
alexandria_type: memory_compact
id: duplicate-compact
project: heterarchy-alexandria
status: CURRENT
created_at: 2026-07-15T00:00:00Z
updated_at: 2026-07-15T01:00:00Z
covered_from: 2026-07-15T00:00:00Z
covered_to: 2026-07-15T01:00:00Z
---
# Duplicate Compact

Old current copy.
""",
            encoding="utf-8",
        )
        (notes_dir / "duplicate-compact.md").write_text(
            """---
alexandria_type: memory_compact
id: duplicate-compact
project: heterarchy-alexandria
status: ARCHIVED
created_at: 2026-07-15T00:00:00Z
updated_at: 2026-07-15T02:00:00Z
covered_from: 2026-07-15T00:00:00Z
covered_to: 2026-07-15T01:00:00Z
archived_at: 2026-07-15T02:00:00Z
---
# Duplicate Compact

Archived lifecycle copy.
""",
            encoding="utf-8",
        )
        service = _service(vault)
        current = await service.create(
            MemoryCompactCreate(
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 7, 16, tzinfo=UTC),
                covered_to=datetime(2026, 7, 16, 1, tzinfo=UTC),
                markdown_body=_compact_body(
                    covered_from=datetime(2026, 7, 16, tzinfo=UTC),
                    covered_to=datetime(2026, 7, 16, 1, tzinfo=UTC),
                ),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[_source_ref("ctx-new")],
            )
        )

        duplicate = await service.get("duplicate-compact")
        listed, total = await service.list_compacts(project="heterarchy-alexandria")

        assert duplicate.status is MemoryCompactStatus.ARCHIVED
        return total, [(item.id, item.status) for item in listed], current.id

    total, listed, current_id = anyio.run(scenario)

    assert total == 2
    assert listed[0] == (current_id, MemoryCompactStatus.CURRENT)
    assert listed[1:] == [("duplicate-compact", MemoryCompactStatus.ARCHIVED)]
