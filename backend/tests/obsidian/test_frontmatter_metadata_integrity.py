"""Frontmatter metadata type-integrity regression tests."""

from __future__ import annotations

import pytest
from app.obsidian.application.notes.obsidian_note_templates import (
    frontmatter_for_save,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
    render_markdown_document,
)
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_boolean_metadata,
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONValue


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([" alpha ", "beta", "", "alpha"], ["alpha", "beta"]),
        ((" alpha ", "beta"), ["alpha", "beta"]),
        (" alpha ", ["alpha"]),
        (None, []),
        ([], []),
        ((), []),
        ("Team(Alpha)", ["Team(Alpha)"]),
    ],
)
def test_string_collection_normalization_accepts_canonical_shapes(
    value: JSONValue,
    expected: list[str],
) -> None:
    assert normalize_string_collection(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        [["nested"]],
        {"alpha": "beta"},
        1,
        ("alpha", 2),
        "('alpha', 'beta')",
        ["('alpha', 'beta')"],
        "()",
        "{'alpha': 'beta'}",
        '["alpha", "beta"]',
        "[['nested']]",
        "set(['alpha'])",
    ],
)
def test_string_collection_normalization_rejects_unsafe_or_invalid_shapes(
    value: JSONValue,
) -> None:
    with pytest.raises(ValueError, match="string collection"):
        normalize_string_collection(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        (" TRUE ", True),
        ("false", False),
        ("False", False),
    ],
)
def test_boolean_metadata_normalization_is_strict(
    value: JSONValue,
    expected: bool,
) -> None:
    assert normalize_boolean_metadata(value) is expected


@pytest.mark.parametrize(
    "value",
    ["yes", "no", "1", "0", "on", "off", "truthy", 1, 0, None],
)
def test_boolean_metadata_normalization_rejects_non_boolean_values(
    value: JSONValue,
) -> None:
    with pytest.raises(ValueError, match="boolean metadata"):
        normalize_boolean_metadata(value)


def test_frontmatter_render_parse_preserves_collection_and_scalar_types() -> None:
    rendered = render_markdown_document(
        {
            "tags": ("Evidence Intelligence", "2026-07-29"),
            "artifact_refs": [],
            "source_of_truth": True,
            "reviewed": False,
            "confidence": None,
            "priority": 3,
            "ratio": 0.5,
            "boolean_like_text": "true",
            "numeric_text": "3",
        },
        "# Body",
    )

    assert "tags:\n  - Evidence Intelligence\n  - 2026-07-29" in rendered
    assert "artifact_refs: []" in rendered
    assert "source_of_truth: true" in rendered
    assert "reviewed: false" in rendered
    assert "confidence: null" in rendered

    parsed = frontmatter_json(parse_markdown_document(rendered).frontmatter)
    assert parsed == {
        "tags": ["Evidence Intelligence", "2026-07-29"],
        "artifact_refs": [],
        "source_of_truth": True,
        "reviewed": False,
        "confidence": None,
        "priority": 3,
        "ratio": 0.5,
        "boolean_like_text": "true",
        "numeric_text": "3",
    }


def test_frontmatter_for_save_normalizes_known_metadata_fields() -> None:
    payload = ObsidianSaveNote(
        title="Metadata Integrity",
        body="# Metadata Integrity",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        tags=(" alpha ", "beta", "alpha", ""),
        frontmatter={
            "artifact_refs": ("artifact-1", "artifact-2", "artifact-1"),
            "evidence_refs": (" evidence-1 ", ""),
            "conflict_set_ids": None,
            "source_of_truth": "TRUE",
            "linked_note_ids": (" note-1 ", "note-1", "note-2"),
            "activate_requested": "false",
            "unrelated_null": None,
            "unrelated_number": 7,
        },
    )

    frontmatter = frontmatter_for_save(
        payload,
        note_id="note-1",
        title=payload.title,
        redaction_warnings=[],
    )

    assert frontmatter["tags"] == ["alpha", "beta"]
    assert frontmatter["artifact_refs"] == ["artifact-1", "artifact-2"]
    assert frontmatter["evidence_refs"] == ["evidence-1"]
    assert frontmatter["conflict_set_ids"] == []
    assert frontmatter["source_of_truth"] is True
    assert frontmatter["linked_note_ids"] == ["note-1", "note-2"]
    assert frontmatter["activate_requested"] is False
    assert frontmatter["unrelated_null"] is None
    assert frontmatter["unrelated_number"] == 7
