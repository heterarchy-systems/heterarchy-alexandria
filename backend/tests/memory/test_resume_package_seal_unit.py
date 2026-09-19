"""Pure-unit tests for resume package sealing and lineage revision selection."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.memory_compacts.lifecycle.memory_compact_policy import (
    missing_current_sections,
)
from app.memory.application.memory_compacts.resume_package.resume_package_assembly import (
    next_lineage_successor,
    resume_package_draft_hash,
    validated_resume_package,
)
from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageDraft,
    ResumePackageEvidenceRef,
    ResumePackageLineage,
    ResumePackageLineageEntry,
)
from app.memory.application.memory_compacts.resume_package.resume_package_markdown import (
    parse_resume_package_markdown,
    render_resume_package_markdown,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
COVERED_FROM = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
COVERED_TO = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)


def _draft(
    *,
    goal: str = "Ship the versioned resume context package",
    summary: str = "Sealed worker handoff",
) -> ResumePackageDraft:
    """Build one deterministic draft for pure-unit scenarios.

    Args:
        goal: Goal override.
        summary: Summary override.

    Returns:
        Resume package draft.
    """
    return ResumePackageDraft(
        project="heterarchy-alexandria",
        goal=goal,
        summary=summary,
        current_state="Everything sealed through the compact path",
        next_single_action="Run the resume package verification gates",
        covered_from=COVERED_FROM,
        covered_to=COVERED_TO,
        lineage=ResumePackageLineage(lineage_id="lineage-1"),
        evidence_context_ids=("ctx-a", "ctx-b"),
    )


def _evidence(
    context_id: str,
    content_hash: str,
) -> ResumePackageEvidenceRef:
    """Build one deterministic evidence reference.

    Args:
        context_id: Stored Context identifier.
        content_hash: Observed content hash.

    Returns:
        Evidence reference.
    """
    return ResumePackageEvidenceRef(
        context_id=context_id,
        content_hash=content_hash,
        source="AGENT:Hermes",
        created_at=NOW,
        observed_updated_at=NOW,
    )


def test_resume_package_draft_hash_is_content_sensitive() -> None:
    """Equal content seals equal hashes; content or evidence changes differ."""
    baseline_draft = _draft()
    baseline_evidence = (
        _evidence("ctx-a", "hash-a"),
        _evidence("ctx-b", "hash-b"),
    )
    baseline = resume_package_draft_hash(baseline_draft, baseline_evidence)
    repeat = resume_package_draft_hash(
        _draft(),
        (
            _evidence("ctx-b", "hash-b"),
            _evidence("ctx-a", "hash-a"),
        ),
    )
    changed_goal = resume_package_draft_hash(
        _draft(goal="Ship a different objective"),
        baseline_evidence,
    )
    changed_evidence = resume_package_draft_hash(
        _draft(),
        (
            _evidence("ctx-a", "hash-a-changed"),
            _evidence("ctx-b", "hash-b"),
        ),
    )

    assert repeat == baseline
    assert changed_goal != baseline
    assert changed_evidence != baseline


def test_next_lineage_successor_picks_max_revision_and_predecessor() -> None:
    """Fresh lineages seal revision one; existing lineages increment."""
    fresh = next_lineage_successor(())
    populated = next_lineage_successor(
        (
            ResumePackageLineageEntry(
                package_id="package-1",
                package_revision=1,
                draft_hash="hash-1",
                updated_at=NOW,
            ),
            ResumePackageLineageEntry(
                package_id="package-3",
                package_revision=3,
                draft_hash="hash-3",
                updated_at=NOW,
            ),
        )
    )

    assert fresh == (1, None)
    assert populated == (4, "package-3")


def test_resume_package_markdown_round_trips_structured_fields() -> None:
    """Render and parse are exact inverses over the validated value space."""
    draft = ResumePackageDraft(
        project="heterarchy-alexandria",
        goal="Ship the versioned resume context package",
        summary="Sealed worker handoff",
        current_state="Everything sealed through the compact path",
        next_single_action="Run the resume package verification gates",
        covered_from=COVERED_FROM,
        covered_to=COVERED_TO,
        lineage=ResumePackageLineage(lineage_id="lineage-1"),
        evidence_context_ids=("ctx-a", "ctx-b"),
        verified_complete=("First verified task",),
        implemented_unverified=("Unverified migration step",),
        unfinished_tasks=("Follow-up refactor",),
        uncertain_results=("Benchmark delta is uncertain",),
        blockers=("Waiting on credentials",),
    )
    evidence_refs = (
        _evidence("ctx-a", "hash-a"),
        _evidence("ctx-b", "hash-b"),
    )
    body = render_resume_package_markdown(
        project=draft.project,
        goal=draft.goal,
        summary=draft.summary,
        current_state=draft.current_state,
        next_single_action=draft.next_single_action,
        covered_from=draft.covered_from,
        covered_to=draft.covered_to,
        accepted_changes=draft.accepted_changes,
        constraints=draft.constraints,
        verified_complete=draft.verified_complete,
        implemented_unverified=draft.implemented_unverified,
        unfinished_tasks=draft.unfinished_tasks,
        uncertain_results=draft.uncertain_results,
        blockers=draft.blockers,
        evidence_refs=evidence_refs,
        lineage_id="lineage-1",
        worker_id="worker-7",
        run_id=None,
        workspace_id=None,
        session_id=None,
        previous_package_id="package-1",
        package_revision=2,
        draft_hash="draft-hash",
    )

    parsed = parse_resume_package_markdown(body)

    assert parsed.goal == draft.goal
    assert parsed.summary == draft.summary
    assert parsed.current_state == draft.current_state
    assert parsed.next_single_action == draft.next_single_action
    assert parsed.verified_complete == draft.verified_complete
    assert parsed.implemented_unverified == draft.implemented_unverified
    assert parsed.unfinished_tasks == draft.unfinished_tasks
    assert parsed.uncertain_results == draft.uncertain_results
    assert parsed.blockers == draft.blockers
    assert parsed.covered_from == COVERED_FROM
    assert parsed.covered_to == COVERED_TO
    assert parsed.evidence_refs == evidence_refs
    assert parsed.lineage_id == "lineage-1"
    assert parsed.worker_id == "worker-7"
    assert parsed.run_id is None
    assert parsed.previous_package_id == "package-1"
    assert parsed.package_revision == 2
    assert parsed.draft_hash == "draft-hash"


def test_rendered_resume_package_body_satisfies_compact_section_policy() -> None:
    """The canonical body must satisfy the CURRENT compact section policy."""
    body = render_resume_package_markdown(
        project="heterarchy-alexandria",
        goal="Ship the versioned resume context package",
        summary="Sealed worker handoff",
        current_state="Everything sealed through the compact path",
        next_single_action="Run the resume package verification gates",
        covered_from=COVERED_FROM,
        covered_to=COVERED_TO,
        accepted_changes=(),
        constraints=(),
        verified_complete=(),
        implemented_unverified=(),
        unfinished_tasks=(),
        uncertain_results=(),
        blockers=(),
        evidence_refs=(_evidence("ctx-a", "hash-a"),),
        lineage_id="lineage-1",
        worker_id=None,
        run_id=None,
        workspace_id=None,
        session_id=None,
        previous_package_id=None,
        package_revision=1,
        draft_hash="draft-hash",
    )

    assert missing_current_sections(body) == []


def test_validated_resume_package_seals_normalized_draft_hash() -> None:
    """Validation normalizes whitespace and binds the hash to the evidence."""
    validated = validated_resume_package(
        _draft(summary="  Sealed worker handoff  "),
        (
            _evidence("ctx-b", "hash-b"),
            _evidence("ctx-a", "hash-a"),
        ),
    )

    assert validated.draft.summary == "Sealed worker handoff"
    assert validated.draft_hash == resume_package_draft_hash(
        validated.draft,
        validated.evidence_refs,
    )
