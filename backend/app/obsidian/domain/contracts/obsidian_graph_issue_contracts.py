"""Contracts for listing graph projection issues with exact source detail."""

from __future__ import annotations

from dataclasses import dataclass

_ISSUE_LIST_MAX_LIMIT = 200
_ISSUE_LIST_DEFAULT_LIMIT = 50


class ObsidianGraphIssueListValidationError(ValueError):
    """Invalid graph issue list query."""

    def __init__(self, message: str) -> None:
        """Initialize the validation error.

        Args:
            message: Human-readable bounded message.
        """
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphIssueListQuery:
    """Bounded query for graph projection issues with exact source detail.

    Cursor is the last edge id of the previous page; ``None`` starts a scan.
    """

    code: str | None = None
    source_note_id: str | None = None
    source_path: str | None = None
    limit: int = _ISSUE_LIST_DEFAULT_LIMIT
    cursor: str | None = None

    def __post_init__(self) -> None:
        """Validate bounded list query fields."""
        if not (1 <= self.limit <= _ISSUE_LIST_MAX_LIMIT):
            raise ObsidianGraphIssueListValidationError(
                f"GRAPH_ISSUE_LIMIT_INVALID: limit must be between 1 and "
                f"{_ISSUE_LIST_MAX_LIMIT}"
            )
        for name in ("code", "source_note_id", "source_path", "cursor"):
            value: object = {
                "code": self.code,
                "source_note_id": self.source_note_id,
                "source_path": self.source_path,
                "cursor": self.cursor,
            }[name]
            if isinstance(value, str) and not value.strip():
                raise ObsidianGraphIssueListValidationError(
                    f"GRAPH_ISSUE_QUERY_INVALID: {name} must not be blank"
                )

    @property
    def max_limit(self) -> int:
        """Return the maximum allowed page size."""
        return _ISSUE_LIST_MAX_LIMIT


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphIssueDetail:
    """One graph projection issue with exact source and target detail.

    ``issue_id`` is a deterministic digest of the issue code and edge
    identity, stable across projection runs: the same broken link yields the
    same issue id, so consecutive seals can distinguish recurring issues from
    new ones without any persistence.
    """

    issue_id: str
    code: str
    edge_id: str
    source_note_id: str
    source_path: str
    source_title: str | None
    target_path: str
    relation: str
    detail: str | None
    projection_run_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphIssueListResult:
    """One bounded page of graph issues plus keyset pagination state."""

    issues: tuple[ObsidianGraphIssueDetail, ...]
    next_cursor: str | None = None
    run_id: str | None = None
