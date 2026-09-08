"""Obsidian HTTP schema conversion tests."""

from __future__ import annotations

import pytest
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.interface.schemas.obsidian.obsidian_note_write_schema import (
    ObsidianSaveNoteRequest,
)
from app.obsidian.interface.schemas.obsidian.obsidian_report_bundle_schema import (
    ObsidianReportBundleRequestSchema,
)
from app.obsidian.interface.schemas.obsidian.obsidian_search_schema import (
    ObsidianSearchRequest,
)
from app.shared.serialization.orjson_codec import dumps_json
from pydantic import ValidationError


def test_obsidian_request_schemas_restore_enum_contracts() -> None:
    """Pydantic enum-value schemas should still emit domain enum contracts."""
    search = ObsidianSearchRequest.model_validate_json(
        dumps_json({"query": "cache", "alexandria_type": "context"})
    )
    save = ObsidianSaveNoteRequest.model_validate_json(
        dumps_json(
            {
                "title": "Smoke",
                "body": "body",
                "alexandria_type": "job_plan",
            }
        )
    )

    assert search.to_query().alexandria_type is AlexandriaNoteType.CONTEXT
    assert search.refresh is False
    assert (
        ObsidianSearchRequest.model_validate_json(
            dumps_json({"query": "cache", "refresh": True})
        ).refresh
        is True
    )
    assert (
        ObsidianSearchRequest.model_validate_json(dumps_json({"query": "cache"}))
        .to_query()
        .alexandria_type
        is None
    )
    assert save.to_command().alexandria_type is AlexandriaNoteType.JOB_PLAN


def test_obsidian_save_schema_normalizes_metadata_at_http_boundary() -> None:
    """HTTP saves should produce typed, canonical metadata before the service."""
    request = ObsidianSaveNoteRequest.model_validate_json(
        dumps_json(
            {
                "title": "Metadata Integrity",
                "body": "# Metadata Integrity",
                "alexandria_type": "context",
                "tags": " Evidence Intelligence ",
                "frontmatter": {
                    "artifact_refs": ["artifact-1", "artifact-1", "artifact-2"],
                    "evidence_refs": ["evidence-1", "evidence-2"],
                    "source_of_truth": "TrUe",
                },
            }
        )
    )

    command = request.to_command()

    assert command.tags == ("Evidence Intelligence",)
    assert command.frontmatter["artifact_refs"] == ["artifact-1", "artifact-2"]
    assert command.frontmatter["evidence_refs"] == ["evidence-1", "evidence-2"]
    assert command.frontmatter["source_of_truth"] is True


@pytest.mark.parametrize(
    "value",
    ["('evidence-1', 'evidence-2')", "()", '["evidence-1"]'],
)
def test_obsidian_save_schema_rejects_legacy_collection_repr(value: str) -> None:
    """HTTP saves must reject collection repr strings after migration."""
    with pytest.raises(ValidationError):
        ObsidianSaveNoteRequest.model_validate_json(
            dumps_json(
                {
                    "title": "Metadata Integrity",
                    "body": "# Metadata Integrity",
                    "alexandria_type": "context",
                    "frontmatter": {"evidence_refs": value},
                }
            )
        )


@pytest.mark.parametrize("value", ["yes", "1", 1])
def test_obsidian_save_schema_rejects_ambiguous_boolean_metadata(
    value: object,
) -> None:
    """HTTP saves must not use permissive truthy coercion for Boolean fields."""
    with pytest.raises(ValidationError):
        ObsidianSaveNoteRequest.model_validate_json(
            dumps_json(
                {
                    "title": "Metadata Integrity",
                    "body": "# Metadata Integrity",
                    "alexandria_type": "context",
                    "frontmatter": {"source_of_truth": value},
                }
            )
        )


def test_report_bundle_schema_applies_managed_context_defaults() -> None:
    """The documented compact Source payload should become a valid Context command."""
    request = ObsidianReportBundleRequestSchema.model_validate_json(
        dumps_json(
            {
                "idempotency_key": "ethereum:2026-08-03",
                "source": {
                    "title": "Ethereum Source",
                    "path": "Contexts/Projects/Ethereum Source.md",
                    "body": "# Ethereum Source",
                    "frontmatter": {"project": "crypto-intelligence"},
                },
                "graph_owners": [
                    {
                        "path": "Indexes/Ethereum Month Index.md",
                        "relation": "contains",
                    }
                ],
            }
        )
    )

    command = request.to_command()

    assert command.source.alexandria_type is AlexandriaNoteType.CONTEXT
    assert command.source.project == "crypto-intelligence"
    assert command.source.frontmatter["scope"] == "PROJECT"
    assert command.graph_owners[0].relation.value == "contains"
