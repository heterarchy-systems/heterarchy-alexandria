"""Typed contracts for Context reindex manifest validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReindexCandidate:
    """One parsed managed note awaiting manifest validation and indexing."""

    path: Path
    payload: ObsidianNoteIndex


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReindexManifestIssue:
    """One candidate rejected by cross-note manifest validation."""

    relative_path: str
    context_id: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReindexManifest:
    """Validated candidates and deterministic per-note rejection details."""

    candidates: tuple[ContextReindexCandidate, ...]
    issues: tuple[ContextReindexManifestIssue, ...]


class ContextReindexManifestValidator(ABC):
    """Validate one complete normalized reindex candidate batch."""

    @abstractmethod
    def validate(
        self,
        candidates: list[ContextReindexCandidate],
    ) -> ContextReindexManifest:
        """Return accepted candidates and deterministic manifest issues.

        Args:
            candidates: Parsed notes from one complete vault scan.

        Returns:
            Validated candidates and structured rejection details.
        """


class UnconfiguredContextReindexManifestValidator(ContextReindexManifestValidator):
    """Fail closed when direct service construction omits the production validator."""

    def validate(
        self,
        candidates: list[ContextReindexCandidate],
    ) -> ContextReindexManifest:
        """Reject reindex execution when the native validator was not composed.

        Args:
            candidates: Parsed notes that cannot safely be validated here.

        Returns:
            Never returns because missing native authority is fatal.

        Raises:
            RuntimeError: Always, because reindex compute must have one configured authority.
        """
        del candidates
        raise RuntimeError(
            "CONTEXT_REINDEX_MANIFEST_VALIDATOR_UNAVAILABLE: native validator is not configured"
        )


UNCONFIGURED_CONTEXT_REINDEX_MANIFEST_VALIDATOR = (
    UnconfiguredContextReindexManifestValidator()
)


def supersedes_context_id(payload: ObsidianNoteIndex) -> str | None:
    """Return the forward supersede reference for a Context note.

    Args:
        payload: Parsed managed note index payload.

    Returns:
        Superseded Context ID, or None.
    """
    if payload.alexandria_type is not AlexandriaNoteType.CONTEXT:
        return None
    return _json_text(payload.frontmatter, "supersedes_context_id")


def manifest_frontmatter_text(payload: ObsidianNoteIndex, key: str) -> str | None:
    """Return one string-only manifest field from normalized frontmatter.

    Args:
        payload: Parsed managed note index payload.
        key: Frontmatter field used by the native manifest wire.

    Returns:
        String value when present with the expected type, otherwise None.
    """
    return _json_text(payload.frontmatter, key)


def _json_text(frontmatter: JSONObject, key: str) -> str | None:
    """Return one frontmatter value only when it is a string.

    Args:
        frontmatter: Normalized frontmatter object.
        key: Field to read.

    Returns:
        String field value, otherwise None.
    """
    value = frontmatter.get(key)
    return value if isinstance(value, str) else None
