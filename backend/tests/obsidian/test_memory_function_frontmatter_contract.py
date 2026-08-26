"""Pure Obsidian frontmatter tests for the orthogonal MemoryFunction axis."""

from __future__ import annotations

import pytest

from app.memory.domain.event_enum.context_enums import (
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    MemoryFunction,
)
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_boundary import (
    validate_context_frontmatter,
)
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    normalized_context_frontmatter,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_identity import (
    ObsidianContextIdentity,
    ObsidianContextProvenance,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianContextLifecycleStatus


def _identity(memory_function: MemoryFunction | None) -> ObsidianContextIdentity:
    """Build a canonical Context identity without invoking native hashing."""
    return ObsidianContextIdentity(
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        status=ObsidianContextLifecycleStatus.ACTIVE,
        provenance=ObsidianContextProvenance(
            source_actor_id=None,
            source_actor_type=ContextSourceType.SYSTEM,
            source_run_id=None,
            external_run_id=None,
            artifact_refs=(),
            evidence_refs=(),
            confidence=ContextImportance.HIGH,
        ),
        content_hash="a" * 64,
        version=1,
        supersedes_context_id=None,
        superseded_by_context_id=None,
        context_kind=ContextKind.DECISION,
        memory_function=memory_function,
        created_at=None,
        updated_at=None,
    )


def test_context_kind_and_memory_function_round_trip_independently() -> None:
    """Document purpose and functional-memory role must remain independent metadata axes."""
    normalized = normalized_context_frontmatter(_identity(MemoryFunction.PROCEDURAL))
    boundary = validate_context_frontmatter(normalized)

    assert boundary.context_kind is ContextKind.DECISION
    assert boundary.memory_function is MemoryFunction.PROCEDURAL


def test_missing_memory_function_remains_backward_compatible() -> None:
    """Legacy Context frontmatter without MemoryFunction must remain readable."""
    normalized = normalized_context_frontmatter(_identity(None))
    boundary = validate_context_frontmatter(normalized)

    assert boundary.context_kind is ContextKind.DECISION
    assert boundary.memory_function is None


def test_invalid_memory_function_fails_closed_at_strict_boundary() -> None:
    """Unknown functional-memory roles must never silently normalize to a valid role."""
    with pytest.raises(ValueError, match="INVALID_MEMORY_FUNCTION"):
        validate_context_frontmatter(
            {
                "scope": "PROJECT",
                "project": "heterarchy-alexandria",
                "visibility": "PROJECT",
                "status": "active",
                "context_kind": "DECISION",
                "memory_function": "WORKING",
            }
        )
