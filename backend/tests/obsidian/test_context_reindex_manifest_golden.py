"""Golden oracle for deterministic Context reindex manifest validation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, Required, TypedDict, cast

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.markdown.paths import canonical_relative_path
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_PATH = _REPOSITORY_ROOT / "native/golden/context_reindex_manifest.v1.json"
_MODIFIED_AT = datetime(2026, 8, 25, tzinfo=UTC)
_IDENTITY_FIELDS = (
    "scope",
    "project",
    "workspace_id",
    "agent_id",
    "user_id",
    "session_id",
)
_RELATION_FIELDS = ("supersedes_context_id", "superseded_by_context_id")


class _CorpusCandidate(TypedDict, total=False):
    """One normalized candidate encoded by the shared golden corpus."""

    note_id: Required[str]
    relative_path: Required[str]
    canonical_relative_path: Required[str]
    alexandria_type: Required[str]
    content_hash: Required[str]
    scope: NotRequired[str]
    project: NotRequired[str]
    workspace_id: NotRequired[str]
    agent_id: NotRequired[str]
    user_id: NotRequired[str]
    session_id: NotRequired[str]
    supersedes_context_id: NotRequired[JSONValue]
    superseded_by_context_id: NotRequired[JSONValue]


class _ExpectedIssue(TypedDict):
    """Exact manifest issue contract frozen by the corpus."""

    relative_path: str
    context_id: str
    message: str


class _ExpectedManifest(TypedDict):
    """Deterministic normalized manifest output used for cross-language parity."""

    accepted_indices: list[int]
    issues: list[_ExpectedIssue]


class _CorpusCase(TypedDict):
    """One named manifest validation scenario."""

    name: str
    candidates: list[_CorpusCandidate]
    expected: _ExpectedManifest


class _Corpus(TypedDict):
    """Versioned shared corpus consumed by Python and Rust parity tests."""

    contract_version: int
    manifest_version: int
    cases: list[_CorpusCase]


def test_context_reindex_manifest_matches_shared_golden_corpus() -> None:
    """Keep native production validation aligned with the frozen pre-cutover corpus."""
    corpus = _load_corpus()

    assert corpus["contract_version"] == 1
    assert corpus["manifest_version"] == 1
    assert len(corpus["cases"]) >= 16

    for case in corpus["cases"]:
        candidates = [_candidate(raw) for raw in case["candidates"]]
        for raw in case["candidates"]:
            assert (
                canonical_relative_path(raw["relative_path"])
                == raw["canonical_relative_path"]
            ), case["name"]

        manifest = create_native_context_reindex_manifest_validator().validate(
            candidates
        )
        candidate_indices = {
            id(candidate): index for index, candidate in enumerate(candidates)
        }
        actual = _ExpectedManifest(
            accepted_indices=[
                candidate_indices[id(candidate)] for candidate in manifest.candidates
            ],
            issues=[
                _ExpectedIssue(
                    relative_path=issue.relative_path,
                    context_id=issue.context_id,
                    message=issue.message,
                )
                for issue in manifest.issues
            ],
        )

        assert actual == case["expected"], case["name"]


def _load_corpus() -> _Corpus:
    """Load the hand-authored versioned manifest parity corpus.

    Returns:
        Typed corpus after a minimal JSON-object boundary check.
    """
    decoded = loads_json(_CORPUS_PATH.read_bytes())
    if not isinstance(decoded, dict):
        raise TypeError("Context reindex manifest corpus must be a JSON object")
    return cast(_Corpus, decoded)


def _candidate(raw: _CorpusCandidate) -> ContextReindexCandidate:
    """Build one production-adapter input from the shared corpus candidate.

    Args:
        raw: Normalized corpus candidate.

    Returns:
        Production manifest candidate carrying a normalized note payload.
    """
    frontmatter: JSONObject = {"content_hash": raw["content_hash"]}
    for field_name in _IDENTITY_FIELDS:
        value = raw.get(field_name)
        if isinstance(value, str):
            frontmatter[field_name] = value
    for field_name in _RELATION_FIELDS:
        if field_name in raw:
            frontmatter[field_name] = raw[field_name]

    body = f"# {raw['note_id']}\n\nGolden manifest candidate."
    project = raw.get("project")
    return ContextReindexCandidate(
        path=Path(raw["relative_path"]),
        payload=ObsidianNoteIndex(
            note_id=raw["note_id"],
            relative_path=raw["relative_path"],
            alexandria_type=AlexandriaNoteType(raw["alexandria_type"]),
            title=raw["note_id"],
            status="active",
            tags=(),
            project=project,
            source="golden-corpus",
            content_hash=raw["content_hash"],
            frontmatter=frontmatter,
            body=body,
            size_bytes=len(body.encode("utf-8")),
            modified_at=_MODIFIED_AT,
            chunks=(),
        ),
    )
