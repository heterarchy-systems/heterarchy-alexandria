"""Source values emitted by verified-upsert projection writers."""

from enum import StrEnum


class ProjectionSignal(StrEnum):
    """Recognized projection observations before result-status mapping."""

    INDEXED = "indexed"
    READY = "ready"
    VERIFIED = "verified"
    STORED = "stored"
    PENDING = "pending"
    UNKNOWN = "unknown"
    STALE = "stale"
    REINDEX_REQUIRED = "reindex_required"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    ERROR = "error"
