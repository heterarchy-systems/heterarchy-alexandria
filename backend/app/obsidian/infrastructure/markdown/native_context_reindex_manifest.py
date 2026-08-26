"""Native Rust adapter for coarse Context reindex-manifest validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
    ContextReindexManifest,
    ContextReindexManifestIssue,
    ContextReindexManifestValidator,
    manifest_frontmatter_text,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.paths import canonical_relative_path
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_MANIFEST_VERSION = 1
_COMPUTE_CONTRACT_VERSION = 1
_RESULT_KEYS = frozenset({"accepted_indices", "issues"})
_ISSUE_KEYS = frozenset({"relative_path", "context_id", "message"})


class _ManifestCandidateWire(TypedDict):
    note_id: str
    relative_path: str
    canonical_relative_path: str
    is_context: bool
    scope: str | None
    project: str | None
    workspace_id: str | None
    agent_id: str | None
    user_id: str | None
    session_id: str | None
    content_hash: str | None
    supersedes_context_id: str | None
    superseded_by_context_id: str | None


class _ManifestRequestWire(TypedDict):
    contract_version: int
    manifest_version: int
    candidates: list[_ManifestCandidateWire]


# protocol-contract: structural-seam
class _NativeContextReindexManifestModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by Context manifest validation."""

    def compute_context_reindex_manifest_json(self, payload: bytes) -> bytes:
        """Validate one normalized candidate batch.

        Args:
            payload: Strict manifest request JSON.

        Returns:
            Strict manifest result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeContextReindexManifestValidator(ContextReindexManifestValidator):
    """Delegate deterministic cross-note manifest validation to Rust."""

    native_module: _NativeContextReindexManifestModule

    def validate(
        self,
        candidates: list[ContextReindexCandidate],
    ) -> ContextReindexManifest:
        """Validate one complete candidate batch in one native call.

        Args:
            candidates: Parsed notes from one complete vault scan.

        Returns:
            Accepted original candidates and deterministic rejection details.

        Raises:
            ValueError: If the native wire contract drifts or returns invalid indices.
        """
        request = _ManifestRequestWire(
            contract_version=_COMPUTE_CONTRACT_VERSION,
            manifest_version=_MANIFEST_VERSION,
            candidates=[_candidate_wire(candidate) for candidate in candidates],
        )
        encoded = self.native_module.compute_context_reindex_manifest_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_manifest(loads_json(encoded), candidates)


def create_native_context_reindex_manifest_validator() -> (
    NativeContextReindexManifestValidator
):
    """Create the fail-closed native Context manifest validator.

    Returns:
        Validator backed by the required native extension.
    """
    module = cast(_NativeContextReindexManifestModule, load_native_compute_module())
    return NativeContextReindexManifestValidator(module)


def _candidate_wire(candidate: ContextReindexCandidate) -> _ManifestCandidateWire:
    """Normalize one Python-owned parsed note into the strict native wire.

    Args:
        candidate: Parsed managed note candidate.

    Returns:
        JSON-serializable normalized deterministic compute input.
    """
    payload = candidate.payload
    return _ManifestCandidateWire(
        note_id=payload.note_id,
        relative_path=payload.relative_path,
        canonical_relative_path=canonical_relative_path(payload.relative_path),
        is_context=payload.alexandria_type is AlexandriaNoteType.CONTEXT,
        scope=manifest_frontmatter_text(payload, "scope"),
        project=manifest_frontmatter_text(payload, "project"),
        workspace_id=manifest_frontmatter_text(payload, "workspace_id"),
        agent_id=manifest_frontmatter_text(payload, "agent_id"),
        user_id=manifest_frontmatter_text(payload, "user_id"),
        session_id=manifest_frontmatter_text(payload, "session_id"),
        content_hash=manifest_frontmatter_text(payload, "content_hash"),
        supersedes_context_id=manifest_frontmatter_text(
            payload, "supersedes_context_id"
        ),
        superseded_by_context_id=manifest_frontmatter_text(
            payload, "superseded_by_context_id"
        ),
    )


def _decode_manifest(
    value: JSONValue,
    candidates: list[ContextReindexCandidate],
) -> ContextReindexManifest:
    """Decode and validate the native manifest result.

    Args:
        value: Decoded native JSON result.
        candidates: Original ordered candidate batch.

    Returns:
        Manifest reconstructed with the original candidate objects.
    """
    root = _object(value, "root")
    if frozenset(root) != _RESULT_KEYS:
        raise ValueError(
            "NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: invalid root fields"
        )
    accepted_indices = _accepted_indices(root.get("accepted_indices"), len(candidates))
    raw_issues = _array(root.get("issues"), "issues")
    issues = tuple(_issue(raw_issue) for raw_issue in raw_issues)
    return ContextReindexManifest(
        candidates=tuple(candidates[index] for index in accepted_indices),
        issues=issues,
    )


def _accepted_indices(value: JSONValue | None, candidate_count: int) -> list[int]:
    """Validate accepted candidate indices returned by native compute.

    Args:
        value: Raw accepted-index array.
        candidate_count: Number of original candidates.

    Returns:
        Ordered unique accepted indices.
    """
    raw_indices = _array(value, "accepted_indices")
    indices: list[int] = []
    seen: set[int] = set()
    for raw_index in raw_indices:
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise ValueError(
                "NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: invalid accepted index"
            )
        if raw_index < 0 or raw_index >= candidate_count or raw_index in seen:
            raise ValueError(
                "NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: invalid accepted index"
            )
        seen.add(raw_index)
        indices.append(raw_index)
    return indices


def _issue(value: JSONValue) -> ContextReindexManifestIssue:
    """Decode one strict native manifest issue.

    Args:
        value: Raw issue JSON value.

    Returns:
        Typed manifest issue.
    """
    issue = _object(value, "issue")
    if frozenset(issue) != _ISSUE_KEYS:
        raise ValueError(
            "NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: invalid issue fields"
        )
    return ContextReindexManifestIssue(
        relative_path=_required_text(issue, "relative_path"),
        context_id=_required_text(issue, "context_id"),
        message=_required_text(issue, "message"),
    )


def _object(value: JSONValue | None, field_name: str) -> JSONObject:
    """Require a JSON object.

    Args:
        value: Decoded JSON value.
        field_name: Diagnostic field name.

    Returns:
        JSON object.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: invalid {field_name}"
        )
    return value


def _array(value: JSONValue | None, field_name: str) -> list[JSONValue]:
    """Require a JSON array.

    Args:
        value: Decoded JSON value.
        field_name: Diagnostic field name.

    Returns:
        JSON array.
    """
    if not isinstance(value, list):
        raise ValueError(
            f"NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: invalid {field_name}"
        )
    return value


def _required_text(value: JSONObject, key: str) -> str:
    """Require one non-empty string result field.

    Args:
        value: Decoded JSON object.
        key: Required field name.

    Returns:
        Non-empty string value.
    """
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: invalid {key}")
    return raw
