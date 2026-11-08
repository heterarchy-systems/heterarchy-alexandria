"""Stable internal labels used by report-bundle policy and evidence."""

from enum import StrEnum


class ReportBundleStage(StrEnum):
    """Stages reported when a report-bundle operation cannot complete."""

    PREFLIGHT_GRAPH_OWNERS = "PREFLIGHT_GRAPH_OWNERS"
    UPSERT_SOURCE = "UPSERT_SOURCE"
    UPDATE_GRAPH_OWNERS = "UPDATE_GRAPH_OWNERS"
    REINDEX_DISABLED = "REINDEX_DISABLED"
    REINDEX = "REINDEX"
    REBUILD_GRAPH_PROJECTION = "REBUILD_GRAPH_PROJECTION"
    VERIFY_INDEX_STATUS = "VERIFY_INDEX_STATUS"
    VERIFY_INCOMING_EDGES = "VERIFY_INCOMING_EDGES"


class ReportBundleMarker(StrEnum):
    """Stable function and write-origin labels in report-bundle evidence."""

    GRAPH_PROJECTION_REBUILD = "graph_projection_rebuild"
    GRAPH_RELATION_LOOKUP = "graph_relation_lookup"
    DUPLICATE_VERIFICATION = "duplicate_verification"
    REPORT_BUNDLE = "report_bundle"


class ReportBundleIdentityField(StrEnum):
    """Frontmatter fields that form declared report identity."""

    REPORT_FAMILY = "report_family"
    REPORT = "report"
    DATE = "date"
    ENTITY = "entity"
    EDITION = "edition"
