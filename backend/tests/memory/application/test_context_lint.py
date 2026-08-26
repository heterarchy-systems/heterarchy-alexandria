"""Behavior tests for Context Harness linting."""

from __future__ import annotations

from app.memory.application.contexts.linting.context_lint import (
    ContextLintInput,
    lint_context,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextStorageStatus,
    MemoryFunction,
)
from app.shared.utils.secret_redaction import BLOCKED_SECRET_PLACEHOLDER


def test_context_lint_returns_saved_when_required_handoff_headings_exist() -> None:
    """Well-structured handoff context should pass without warnings."""
    result = lint_context(
        ContextLintInput(
            kind=ContextKind.HANDOFF,
            title="Sprint handoff",
            summary="Ready for next agent.",
            content="""# Sprint Handoff

## Summary
Ready for next agent.

## Current State
Done.

## Next Actions
1. Continue.

## Restore Prompt
Continue from here.
""",
            project="heterarchy-alexandria",
            source_agent="Hermes",
            tags=["handoff"],
        )
    )

    assert result.ok is True
    assert result.status is ContextStorageStatus.SAVED
    assert result.score == 100
    assert result.errors == ()
    assert result.warnings == ()


def test_context_lint_marks_low_quality_context_for_review() -> None:
    """Missing structure should be saved into review status rather than treated as clean."""
    result = lint_context(
        ContextLintInput(
            kind=ContextKind.HANDOFF,
            title="Thin handoff",
            summary=None,
            content="short note",
            project=None,
            source_agent="Hermes",
            tags=[],
        )
    )

    assert result.ok is True
    assert result.status is ContextStorageStatus.PENDING_REVIEW
    assert "quality score below review threshold" in result.warnings


def test_context_lint_blocks_private_key_content() -> None:
    """Private key blocks should not be persisted by the harness."""
    result = lint_context(
        ContextLintInput(
            kind=ContextKind.MEMORY,
            title="Unsafe memory",
            summary="Contains secret.",
            content="""# Unsafe

## Summary
Contains secret.

## Restore Prompt
No.

-----BEGIN PRIVATE KEY-----
abc
-----END PRIVATE KEY-----
""",
            project=None,
            source_agent="Hermes",
            tags=[],
        )
    )

    assert result.ok is False
    assert result.status is ContextStorageStatus.BLOCKED_SECRET_RISK
    assert "high-risk secret content cannot be saved raw" in result.errors
    assert result.redacted_content == BLOCKED_SECRET_PLACEHOLDER
    assert "BEGIN PRIVATE KEY" not in result.redacted_content


def test_context_lint_preserves_optional_memory_function() -> None:
    """MemoryFunction remains optional while explicit roles survive normalization."""
    legacy = lint_context(
        ContextLintInput(
            kind=ContextKind.MEMORY,
            title="Legacy memory",
            summary="Legacy memory.",
            content="## Summary\nLegacy memory.\n\n## Restore Prompt\nOpen it.",
            project="heterarchy-alexandria",
        )
    )
    procedural = lint_context(
        ContextLintInput(
            kind=ContextKind.DECISION,
            memory_function=MemoryFunction.PROCEDURAL,
            title="Procedure decision",
            summary="Procedure decision.",
            content=(
                "## Summary\nProcedure decision.\n\n"
                "## Key Decisions\nUse the procedure.\n\n"
                "## Evidence\nValidated."
            ),
            project="heterarchy-alexandria",
        )
    )

    assert legacy.normalized["memory_function"] is None
    assert procedural.normalized["kind"] is ContextKind.DECISION
    assert procedural.normalized["memory_function"] is MemoryFunction.PROCEDURAL
