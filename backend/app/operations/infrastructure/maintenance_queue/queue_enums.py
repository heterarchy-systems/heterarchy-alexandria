"""Symbolic replies returned by maintenance queue Lua operations."""

from __future__ import annotations

from enum import StrEnum


class SubmissionReply(StrEnum):
    """Raw replies returned by the enqueue script."""

    RATE_LIMITED = "RATE_LIMITED"
    QUEUED = "QUEUED"
    DEDUPLICATED = "DEDUPLICATED"


class DeadLetterTransitionReply(StrEnum):
    """Raw replies returned by dead-letter lifecycle scripts."""

    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    QUEUED = "QUEUED"
    IDEMPOTENT = "IDEMPOTENT"
    RETIRING = "RETIRING"
    RETIRED = "RETIRED"
    ALREADY_RETIRED = "ALREADY_RETIRED"
