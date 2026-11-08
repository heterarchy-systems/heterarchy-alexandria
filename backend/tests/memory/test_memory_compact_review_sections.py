"""Nested Markdown section boundaries in deterministic compact review."""

from dataclasses import replace

import pytest
from tests.memory.test_memory_compact_service import _create

from app.memory.application.memory_compacts.lifecycle.memory_compact_candidate import (
    candidate_compact,
)
from app.memory.application.memory_compacts.review.memory_compact_review import (
    review_memory_compact,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus


@pytest.mark.parametrize(
    ("body", "expected_score", "expected_reasons"),
    [
        pytest.param(
            "# Project compact\n\n## Current State\n\n"
            "### Runtime\n\n#### Verification\n- Runtime checks are complete.\n",
            2,
            (),
            id="nested-body-belongs-to-parent",
        ),
        pytest.param(
            "## Current State\n\n### Verified runtime and index state\n",
            0,
            ("current_state_missing",),
            id="empty-child-heading-is-not-body",
        ),
        pytest.param(
            "## Current State\n\n### Runtime\n\n"
            "## Next Actions\n- Continue the bounded repair.\n",
            0,
            ("current_state_missing",),
            id="peer-heading-ends-section",
        ),
        pytest.param(
            "## Current State\n\n### Runtime\n\n"
            "# Next Actions\n- Continue the bounded repair.\n",
            0,
            ("current_state_missing",),
            id="ancestor-heading-ends-section",
        ),
    ],
)
def test_review_respects_nested_section_boundaries(
    body: str,
    expected_score: int,
    expected_reasons: tuple[str, ...],
) -> None:
    """Only actual body inside the Current State subtree satisfies its rubric."""
    compact = candidate_compact(
        replace(_create(MemoryCompactStatus.DRAFT), markdown_body=body)
    )

    review = review_memory_compact(compact)
    score = next(item for item in review.scores if item.code == "current_state")

    assert score.score == expected_score
    assert score.reasons == expected_reasons
