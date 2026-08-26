"""Projection-integrity read models for Obsidian-backed Context recall."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextProjectionIntegrityFailure:
    """Aggregated machine-readable projection failure count."""

    code: str
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextProjectionIntegritySnapshot:
    """Persisted full-index projection validation plus current source freshness."""

    checked: bool
    available: bool
    source_revision: str | None
    current_source_revision: str | None
    scanned_count: int
    valid_count: int
    invalid_count: int
    failures: tuple[ContextProjectionIntegrityFailure, ...]
    checked_at: datetime | None
    stale: bool

    @property
    def healthy(self) -> bool:
        """Return whether the persisted projection snapshot is current and clean.

        Returns:
            True when a checked snapshot is available, fresh, and has no invalid notes.
        """
        return (
            self.checked
            and self.available
            and not self.stale
            and self.invalid_count == 0
            and self.source_revision == self.current_source_revision
        )


def unchecked_context_projection_integrity_snapshot() -> (
    ContextProjectionIntegritySnapshot
):
    """Return a neutral projection snapshot for legacy construction boundaries.

    Returns:
        Unchecked snapshot with no asserted projection-integrity evidence.
    """
    return ContextProjectionIntegritySnapshot(
        checked=False,
        available=False,
        source_revision=None,
        current_source_revision=None,
        scanned_count=0,
        valid_count=0,
        invalid_count=0,
        failures=(),
        checked_at=None,
        stale=False,
    )
