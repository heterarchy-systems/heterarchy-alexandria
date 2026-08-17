"""Search-first skill-library sufficiency evaluator tests."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
from app.librarian.application.skill_library_search_service import (
    SkillLibrarySearchService,
)
from app.librarian.application.skill_library_search_contracts import (
    SkillCapabilityBrief,
    SkillSearchDecision,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.obsidian.domain.entities.obsidian_note import ObsidianNote, ObsidianSearchHit
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)

_NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class FakeSkillSearchBackend:
    """Fake Obsidian search backend for deterministic evaluator tests."""

    def __init__(self, hits: list[ObsidianSearchHit], *, fail: bool = False) -> None:
        """Initialize fake search behavior."""
        self.hits = hits
        self.fail = fail
        self.queries = []

    async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
        """Return configured hits or raise a search failure."""
        self.queries.append((query, refresh))
        if self.fail:
            raise RuntimeError("index unavailable")
        return list(self.hits)


def _note(
    *,
    status: str = "active",
    frontmatter: dict[str, object] | None = None,
    body: str | None = None,
) -> ObsidianNote:
    return ObsidianNote(
        note_id="skill_http_boundary_fake",
        relative_path="Alexandria/Skills/Drafts/HTTP Boundary Fake.md",
        alexandria_type=AlexandriaNoteType.SKILL,
        title="HTTP Boundary Fake",
        status=status,
        tags=["skill-acquisition", "testing"],
        project="heterarchy-alexandria",
        source="skill_acquisition",
        content_hash="hash",
        frontmatter={
            "version": "1.0.0",
            "required_tools": ["pytest"],
            "risk_level": "LOW",
            "evidence_urls": ["https://example.com/http-fake"],
            **(frontmatter or {}),
        },
        body=body
        or (
            "# HTTP Boundary Fake\n\n"
            "## Purpose\nBuild deterministic HTTP boundary fakes.\n\n"
            "## Procedure\nUse pytest and HTTP fakes at the boundary.\n"
        ),
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=123,
        modified_at=_NOW,
        indexed_at=_NOW,
    )


def _hit(note: ObsidianNote, *, score: float = 4.0) -> ObsidianSearchHit:
    return ObsidianSearchHit(
        note=note,
        excerpt="HTTP boundary fake pytest procedure",
        score=score,
    )


def test_skill_library_search_returns_sufficient_active_skill() -> None:
    """Active compatible skill notes should prevent a new acquisition job."""

    async def run_case():  # type: ignore[no-untyped-def]
        backend = FakeSkillSearchBackend([_hit(_note())])
        result = await SkillLibrarySearchService(backend).search_first(
            SkillCapabilityBrief(
                capability="HTTP boundary fake",
                task_goal="Replace brittle HTTP tests",
                project="heterarchy-alexandria",
                required_tools=["pytest"],
                risk_tolerance=RiskLevel.MEDIUM,
            )
        )
        return result, backend.queries

    result, queries = anyio.run(run_case)

    assert result.decision is SkillSearchDecision.FOUND_SUFFICIENT
    assert result.gaps == ()
    assert result.candidates[0].sufficiency_score == 10
    assert result.candidates[0].recommended_action == (
        "Reuse this skill for the current task."
    )
    assert result.candidates[0].hard_gates == {
        "active_status": {
            "passed": True,
            "actual": "active",
            "required": "active",
        },
        "required_tools": {
            "passed": True,
            "missing": [],
        },
        "risk_tolerance": {
            "passed": True,
            "actual": "LOW",
            "maximum": "MEDIUM",
        },
        "procedure_section": {
            "passed": True,
        },
        "brief_match": {
            "passed": True,
            "matched_terms": ["http boundary fake", "pytest", "http"],
        },
        "evidence": {
            "passed": True,
        },
    }
    assert result.decision_explanation == {
        "candidate_count": 1,
        "candidate_ids": ["skill_http_boundary_fake"],
        "scores": [{"id": "skill_http_boundary_fake", "sufficiency_score": 10}],
        "hard_gates": {
            "skill_http_boundary_fake": result.candidates[0].hard_gates,
        },
        "match_reasons": {
            "skill_http_boundary_fake": list(result.candidates[0].why_match),
        },
        "gaps": [],
        "limitations": {
            "skill_http_boundary_fake": [],
        },
    }
    assert result.handoff is not None
    assert result.handoff["decision"] == "existing_skill_found"
    assert result.handoff["skill"] == {
        "id": "skill_http_boundary_fake",
        "title": "HTTP Boundary Fake",
        "path": "Alexandria/Skills/Drafts/HTTP Boundary Fake.md",
        "status": "active",
        "version": "1.0.0",
        "risk_level": "LOW",
        "required_tools": ["pytest"],
    }
    assert result.handoff["current_task"]["resume_summary"] == (
        "Replace brittle HTTP tests"
    )
    query, refresh = queries[0]
    assert query.alexandria_type is AlexandriaNoteType.SKILL
    assert query.project == "heterarchy-alexandria"
    assert refresh is True


def test_skill_library_search_marks_draft_skill_partial() -> None:
    """Draft skill notes are reusable context but not sufficient for auto-apply."""

    async def run_case():  # type: ignore[no-untyped-def]
        backend = FakeSkillSearchBackend([_hit(_note(status="draft"))])
        return await SkillLibrarySearchService(backend).search_first(
            SkillCapabilityBrief(
                capability="HTTP boundary fake",
                project="heterarchy-alexandria",
                required_tools=["pytest"],
            )
        )

    result = anyio.run(run_case)

    assert result.decision is SkillSearchDecision.FOUND_PARTIAL
    assert result.candidates[0].status == "draft"
    assert result.handoff is not None
    assert result.handoff["decision"] == "existing_skill_found"
    assert result.handoff["skill"]["status"] == "draft"
    assert result.handoff["reuse"]["limitations"] == [
        "skill status is draft; human review is required before reuse"
    ]
    assert result.candidates[0].hard_gates["active_status"] == {
        "passed": False,
        "actual": "draft",
        "required": "active",
    }
    assert result.gaps == (
        "skill status is draft; human review is required before reuse",
    )


def test_skill_library_search_rediscovers_completed_draft_skill_for_reuse_handoff() -> (
    None
):
    """Completed draft skills should be found on the next identical capability request."""

    async def run_case():  # type: ignore[no-untyped-def]
        completed_note = _note(
            status="draft",
            frontmatter={
                "source_job_id": "skill-acquisition-1",
                "requested_status": "draft",
            },
        )
        backend = FakeSkillSearchBackend([_hit(completed_note)])
        return await SkillLibrarySearchService(backend).search_first(
            SkillCapabilityBrief(
                capability="HTTP boundary fake",
                task_goal="Replace brittle HTTP tests",
                project="heterarchy-alexandria",
                required_tools=["pytest"],
            )
        )

    result = anyio.run(run_case)

    assert result.decision is SkillSearchDecision.FOUND_PARTIAL
    assert result.handoff is not None
    assert result.handoff["decision"] == "existing_skill_found"
    assert result.handoff["skill"]["id"] == "skill_http_boundary_fake"
    assert result.handoff["current_task"]["next_steps"] == [
        "Open and apply existing skill note: Alexandria/Skills/Drafts/HTTP Boundary Fake.md",
        "Do not start librarian acquisition for this capability unless reuse fails.",
    ]
    assert result.handoff["reuse"]["limitations"] == [
        "skill status is draft; human review is required before reuse"
    ]


def test_skill_library_search_reports_unavailable_index_distinct_from_not_found() -> (
    None
):
    """Search backend failure should not be interpreted as no skill exists."""

    async def run_case():  # type: ignore[no-untyped-def]
        backend = FakeSkillSearchBackend([], fail=True)
        return await SkillLibrarySearchService(backend).search_first(
            SkillCapabilityBrief(capability="browser automation")
        )

    result = anyio.run(run_case)

    assert result.decision is SkillSearchDecision.SEARCH_UNAVAILABLE
    assert result.candidates == ()
    assert result.search_error == "index unavailable"
    assert result.gaps == ("Skill library search failed",)
    assert result.decision_explanation == {
        "candidate_count": 0,
        "candidate_ids": [],
        "scores": [],
        "hard_gates": {},
        "match_reasons": {},
        "gaps": ["Skill library search failed"],
        "limitations": ["Skill library search unavailable: index unavailable"],
    }
    assert result.handoff is not None
    assert result.handoff["decision"] == "skill_search_repair_required"
    assert result.handoff["repair"]["tools"] == [
        "alexandria_memory_steward_readiness",
        "alexandria_reindex_vault",
    ]
