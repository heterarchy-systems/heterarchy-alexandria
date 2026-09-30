"""Mutation outcome statuses for durable agent-facing write receipts."""

from __future__ import annotations

from enum import StrEnum


class ObsidianMutationOutcomeStatus(StrEnum):
    """Retry-safety verdict for one previously attempted logical mutation."""

    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
