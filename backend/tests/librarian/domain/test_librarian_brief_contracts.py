"""Librarian brief domain contract tests."""

from __future__ import annotations

import pytest
from app.librarian.domain.entities.budget_policy import BudgetPolicy
from app.librarian.domain.entities.librarian_brief import LibrarianBrief
from app.librarian.domain.entities.source_ref import SourceRef, SourceRefType
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError


def test_budget_policy_rejects_non_positive_limits() -> None:
    """Budget policy should reject packet budgets that cannot hold source refs."""
    with pytest.raises(LibrarianValidationError, match="max_input_chars"):
        BudgetPolicy(max_input_chars=0, max_source_refs=5)

    with pytest.raises(LibrarianValidationError, match="max_source_refs"):
        BudgetPolicy(max_input_chars=1000, max_source_refs=0)


def test_librarian_brief_payload_preserves_budget_and_source_refs() -> None:
    """Librarian brief should serialize compact packet boundaries without raw dicts."""
    source_ref = SourceRef(
        source_type=SourceRefType.CONTEXT,
        source_id="ctx-1",
        title="OAuth decision",
        detail_path="/memory/contexts/ctx-1",
        preview="Use PKCE for callbacks.",
    )
    policy = BudgetPolicy(max_input_chars=1200, max_source_refs=3)
    brief = LibrarianBrief(
        prompt="Which OAuth skill should Hermes use?",
        project="heterarchy-alexandria",
        packet_markdown="# Packet\nUse compact evidence only.",
        source_refs=(source_ref,),
        budget_policy=policy,
    )

    payload = brief.to_payload()

    assert payload == {
        "prompt": "Which OAuth skill should Hermes use?",
        "project": "heterarchy-alexandria",
        "packet_markdown": "# Packet\nUse compact evidence only.",
        "source_refs": [source_ref.to_payload()],
        "budget_policy": policy.to_payload(),
    }
