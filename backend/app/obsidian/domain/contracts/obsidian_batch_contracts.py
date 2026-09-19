"""Bounded batch note operation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.shared.types.extra_types import JSONObject

BATCH_MAX_OPERATIONS = 50


class BatchValidationError(ValueError):
    """Invalid batch request (size, selector, or operation shape)."""

    def __init__(self, message: str) -> None:
        """Initialize the validation error.

        Args:
            message: Human-readable bounded message.
        """
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchReadSelector:
    """One exact note selector for a batch read."""

    path: str | None = None
    note_id: str | None = None

    def __post_init__(self) -> None:
        """Require exactly one selector dimension per item."""
        if (self.path is None) == (self.note_id is None):
            raise BatchValidationError(
                "BATCH_SELECTOR_INVALID: exactly one of path or note_id is required"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchWriteOperation:
    """One per-item CAS write operation inside a batch."""

    op: str
    title: str
    body: str
    relative_path: str
    note_id: str | None = None
    expected_content_hash: str | None = None
    frontmatter: JSONObject = field(default_factory=dict)

    def command_parts(self) -> tuple[str, str, str, str, str | None, str | None]:
        """Return (op, title, body, relative_path, note_id, expected_hash).

        Returns:
            Tuple of operation fields for command construction.
        """
        return (
            self.op,
            self.title,
            self.body,
            self.relative_path,
            self.note_id,
            self.expected_content_hash,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchReadItemResult:
    """Independent per-item read outcome."""

    path: str | None
    note_id: str | None
    status: str
    note: ObsidianNote | None = None
    parse_error: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchReadResult:
    """Aggregate batch read result."""

    items: tuple[BatchReadItemResult, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchValidateItemResult:
    """Independent per-item link validation outcome."""

    path: str | None
    note_id: str | None
    status: str
    exists: bool = False
    parsed_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchValidateResult:
    """Aggregate batch link validation result."""

    items: tuple[BatchValidateItemResult, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchWriteItemResult:
    """Independent per-item write outcome."""

    path: str
    note_id: str | None
    status: str
    content_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchWriteResult:
    """Aggregate batch write result with per-item independent outcomes."""

    items: tuple[BatchWriteItemResult, ...]

    @property
    def succeeded(self) -> int:
        """Return the number of successful writes.

        Returns:
            Count of updated or created items.
        """
        return sum(1 for item in self.items if item.status in {"updated", "created"})

    @property
    def conflicted(self) -> int:
        """Return the number of CAS conflicts.

        Returns:
            Count of conflicted items.
        """
        return sum(1 for item in self.items if item.status == "conflict")

    @property
    def failed(self) -> int:
        """Return the number of invalid or failed items.

        Returns:
            Count of non-success, non-conflict failures.
        """
        return sum(
            1 for item in self.items if item.status in {"invalid", "not_found", "error"}
        )
