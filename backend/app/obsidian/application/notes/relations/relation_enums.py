"""Closed relation issue and projection status vocabularies."""

from __future__ import annotations

from enum import StrEnum


class RelationIssueCode(StrEnum):
    """Stable issue codes emitted by relation application operations."""

    PROJECTION_COMMIT_FAILED = "PROJECTION_COMMIT_FAILED"
    MUTATION_OUTCOME_RESOLVED = "MUTATION_OUTCOME_RESOLVED"
    GRAPH_PROJECTION_REBUILD_FAILED = "GRAPH_PROJECTION_REBUILD_FAILED"
    DERIVED_INDEX_COMMIT_FAILED = "DERIVED_INDEX_COMMIT_FAILED"
    DERIVED_INDEX_READBACK_FAILED = "DERIVED_INDEX_READBACK_FAILED"
    GRAPH_PROJECTION_READ_FAILED = "GRAPH_PROJECTION_READ_FAILED"
    GRAPH_RELATED_READ_FAILED = "GRAPH_RELATED_READ_FAILED"
    GRAPH_EDGE_NOT_VERIFIED = "GRAPH_EDGE_NOT_VERIFIED"
    GRAPH_PROJECTION_SOURCE_ISSUES = "GRAPH_PROJECTION_SOURCE_ISSUES"


class RelationIssueCapability(StrEnum):
    """Stable capability names attached to relation issue evidence."""

    METADATA_AND_EDGE_INDEX = "metadata_and_edge_index"
    CANONICAL_RELATION_WRITE = "canonical_relation_write"
    GRAPH_PROJECTION = "graph_projection"
    RELATED_NOTE_READ = "related_note_read"


class RelationProjectionStatus(StrEnum):
    """Graph projection readback states for one relation verification."""

    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
