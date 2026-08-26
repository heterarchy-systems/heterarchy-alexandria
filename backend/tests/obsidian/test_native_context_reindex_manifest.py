"""Strict adapter contracts for Rust-authoritative Context reindex manifests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    NativeContextReindexManifestValidator,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue


class _NativeManifestModule:
    """Deterministic fake for the narrow native manifest extension surface."""

    def __init__(self, result: JSONValue) -> None:
        self.result = result
        self.requests: list[bytes] = []

    def compute_contract_version(self) -> int:
        return 1

    def compute_context_reindex_manifest_json(self, payload: bytes) -> bytes:
        self.requests.append(payload)
        return dumps_json(self.result)


def test_native_manifest_adapter_sends_one_normalized_batch_and_restores_candidates() -> (
    None
):
    """One coarse native call must preserve Python-owned path normalization and object identity."""
    native = _NativeManifestModule(
        {
            "accepted_indices": [1, 0],
            "issues": [
                {
                    "relative_path": "Contexts/Rejected.md",
                    "context_id": "ctx-rejected",
                    "message": "INVALID_SUPERSEDE: safe diagnostic",
                }
            ],
        }
    )
    first = _candidate(
        note_id="ctx-first",
        relative_path="Contexts/기능/Café.md",
        supersedes_context_id=7,
    )
    second = _candidate(
        note_id="skill-second",
        relative_path="Jobs/Skills/Second.md",
        alexandria_type=AlexandriaNoteType.SKILL,
    )

    manifest = NativeContextReindexManifestValidator(native).validate([first, second])

    assert manifest.candidates == (second, first)
    assert manifest.issues[0].message == "INVALID_SUPERSEDE: safe diagnostic"
    assert len(native.requests) == 1
    decoded = loads_json(native.requests[0])
    assert isinstance(decoded, dict)
    assert decoded["contract_version"] == 1
    assert decoded["manifest_version"] == 1
    raw_candidates = decoded["candidates"]
    assert isinstance(raw_candidates, list)
    assert raw_candidates[0] == {
        "note_id": "ctx-first",
        "relative_path": "Contexts/기능/Café.md",
        "canonical_relative_path": "Contexts/기능/Café.md",
        "is_context": True,
        "scope": "GLOBAL",
        "project": None,
        "workspace_id": None,
        "agent_id": None,
        "user_id": None,
        "session_id": None,
        "content_hash": "hash-ctx-first",
        "supersedes_context_id": None,
        "superseded_by_context_id": None,
    }
    assert isinstance(raw_candidates[1], dict)
    assert raw_candidates[1]["is_context"] is False


@pytest.mark.parametrize(
    "accepted_indices",
    [
        [True],
        [-1],
        [2],
        [0, 0],
        ["0"],
    ],
)
def test_native_manifest_adapter_rejects_invalid_accepted_indices(
    accepted_indices: list[JSONValue],
) -> None:
    """Native result indices must remain unique in-range integers, never bool/string aliases."""
    native = _NativeManifestModule({"accepted_indices": accepted_indices, "issues": []})

    with pytest.raises(ValueError, match="invalid accepted index"):
        NativeContextReindexManifestValidator(native).validate(
            [_candidate(note_id="ctx-one", relative_path="Contexts/One.md")]
        )


@pytest.mark.parametrize(
    "result",
    [
        {"accepted_indices": [], "issues": [], "extra": True},
        {
            "accepted_indices": [],
            "issues": [
                {"relative_path": "x", "context_id": "y", "message": "z", "extra": True}
            ],
        },
        {"accepted_indices": {}, "issues": []},
        {"accepted_indices": [], "issues": {}},
    ],
)
def test_native_manifest_adapter_rejects_wire_shape_drift(result: JSONValue) -> None:
    """Unknown or mistyped native result shapes must fail closed before indexing."""
    native = _NativeManifestModule(result)

    with pytest.raises(
        ValueError, match="NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR"
    ):
        NativeContextReindexManifestValidator(native).validate(
            [_candidate(note_id="ctx-one", relative_path="Contexts/One.md")]
        )


def _candidate(
    *,
    note_id: str,
    relative_path: str,
    alexandria_type: AlexandriaNoteType = AlexandriaNoteType.CONTEXT,
    supersedes_context_id: JSONValue | None = None,
) -> ContextReindexCandidate:
    """Build one normalized manifest candidate for adapter contract tests.

    Args:
        note_id: Stable candidate identity.
        relative_path: Original logical relative path.
        alexandria_type: Managed-note type.
        supersedes_context_id: Optional deliberately typed or mistyped relation value.

    Returns:
        Candidate carrying a minimal indexed-note payload.
    """
    frontmatter: dict[str, JSONValue] = {
        "scope": "GLOBAL",
        "content_hash": f"hash-{note_id}",
    }
    if supersedes_context_id is not None:
        frontmatter["supersedes_context_id"] = supersedes_context_id
    body = f"# {note_id}"
    return ContextReindexCandidate(
        path=Path(relative_path),
        payload=ObsidianNoteIndex(
            note_id=note_id,
            relative_path=relative_path,
            alexandria_type=alexandria_type,
            title=note_id,
            status="active",
            tags=(),
            project=None,
            source="adapter-test",
            content_hash=f"hash-{note_id}",
            frontmatter=frontmatter,
            body=body,
            size_bytes=len(body.encode("utf-8")),
            modified_at=datetime(2026, 8, 25, tzinfo=UTC),
            chunks=(),
        ),
    )
