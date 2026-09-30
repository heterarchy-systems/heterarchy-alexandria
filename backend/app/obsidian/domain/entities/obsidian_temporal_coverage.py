"""Typed read payloads for temporal coverage evidence."""

from typing import TypedDict


class TemporalCoverageRow(TypedDict):
    """Coverage state for each family on one target date."""

    date: str
    iso_week: str
    ordinal_week: str
    families: dict[str, str]


class TemporalSourceEvidence(TypedDict):
    """Packet presence and ingestion evidence, with unknown time explicit."""

    family: str
    target_date: str
    source_created_at: str | None
    ingestion_date: str | None


class TemporalCoveragePayload(TypedDict):
    """Bounded coverage matrix and closeability evidence."""

    project: str
    timezone: str
    start_date: str
    end_date: str
    matrix: list[TemporalCoverageRow]
    closable_daily: list[str]
    open_daily: list[str]
    missing_expected_sources: list[dict[str, str]]
    late_backfills: list[dict[str, str | None]]
    weekly_close_due: bool
    monthly_close_due: bool
    unparsed_note_count: int
    boundary_policy: dict[str, str]
    source_evidence: list[TemporalSourceEvidence]
