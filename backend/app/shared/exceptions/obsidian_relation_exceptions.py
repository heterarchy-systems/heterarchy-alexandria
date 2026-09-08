"""Stable route-safe failures for the high-level relation operation."""

from __future__ import annotations

from app.shared.exceptions.obsidian_exceptions import ObsidianDomainError
from app.shared.types.extra_types import JSONObject


class ObsidianRelateError(ObsidianDomainError):
    """Base failure carrying a stable relation-operation error code."""

    status_code: int = 422

    def __init__(self, code: str, message: str, recommended_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.recommended_action = recommended_action

    def route_detail(self) -> JSONObject:
        """Return bounded actionable error details for HTTP/MCP callers."""
        return {
            "error_code": self.code,
            "cause": str(self),
            "affected_capability": "relation_write",
            "retryable": False,
            "safe_next_action": self.recommended_action,
            "mutation_performed": False,
        }


class ObsidianRelateTargetNotFoundError(ObsidianRelateError):
    """Raised when relate would need to create an implicit target note."""

    status_code = 404

    def __init__(self, target_note_id: str) -> None:
        super().__init__(
            "RELATE_TARGET_NOT_FOUND",
            f"target note does not exist: {target_note_id}",
            "read or create the target note explicitly, then retry relate",
        )


class ObsidianRelateSelfEdgeError(ObsidianRelateError):
    """Raised when source and target identities are equal."""

    def __init__(self, note_id: str) -> None:
        super().__init__(
            "RELATE_SELF_EDGE",
            f"source and target must differ: {note_id}",
            "choose a distinct existing target note",
        )


class ObsidianRelateInvalidRelationError(ObsidianRelateError):
    """Raised when a body-derived wikilink is requested as a typed relation."""

    def __init__(self, relation: str) -> None:
        super().__init__(
            "RELATE_INVALID_RELATION",
            f"relation cannot be mutated by relate: {relation}",
            "use a supported frontmatter relation type",
        )
