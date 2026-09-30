"""HTTP/MCP contracts for deterministic temporal coverage."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.obsidian.domain.entities.obsidian_temporal_coverage import (
    TemporalCoveragePayload,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)

_ISO_DATE = StringConstraints(
    strict=True, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"
)


class ObsidianTemporalCoverageExclusion(StrictSchemaModel):
    """One (family, date) pair that is expected to have no packet."""

    family: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        described_field("Report family that is not expected on this date."),
    ]
    date: Annotated[str, _ISO_DATE, described_field("Date the family is not expected.")]


class ObsidianTemporalCoverageRequest(StrictSchemaModel):
    """One deterministic temporal coverage question over managed packets."""

    project: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=255),
        described_field("Project identity whose report packets are evaluated."),
    ]
    start_date: Annotated[
        str, _ISO_DATE, described_field("Inclusive ISO range start date.")
    ]
    end_date: Annotated[
        str, _ISO_DATE, described_field("Inclusive ISO range end date.")
    ]
    families: Annotated[
        list[str],
        described_field(
            "Expected report families; empty means report only observed families.",
            max_length=50,
        ),
    ] = schema_list_default()
    not_expected: Annotated[
        list[ObsidianTemporalCoverageExclusion],
        described_field(
            "(family, date) entries that are NOT_EXPECTED rather than MISSING, "
            "such as market holidays.",
            max_length=18300,
        ),
    ] = schema_list_default()
    timezone: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=64),
        described_field("IANA timezone for open-day and week boundary math."),
    ] = "Asia/Seoul"


class ObsidianTemporalCoverageRowResponse(StrictSchemaModel):
    """One date's coverage across the evaluated report families."""

    date: Annotated[str, _ISO_DATE, described_field("Coverage date.")]
    iso_week: Annotated[str, described_field("ISO-8601 week label for this date.")]
    ordinal_week: Annotated[
        str, described_field("Month-ordinal week label for this date.")
    ]
    families: Annotated[
        dict[str, str],
        described_field(
            "Per-family state: COMPLETE, BACKFILL, MISSING, NOT_EXPECTED, or OPEN."
        ),
    ]


class TemporalSourceEvidenceResponse(StrictSchemaModel):
    """Observed packet time evidence independent of its target date."""

    family: Annotated[str, described_field("Observed report family.")]
    target_date: Annotated[str, _ISO_DATE, described_field("Source target date.")]
    source_created_at: Annotated[
        str | None, described_field("Aware source ingestion timestamp, or null.")
    ]
    ingestion_date: Annotated[
        str | None,
        described_field("Ingestion date in the requested timezone, or null."),
    ]


class ObsidianTemporalCoverageResponse(StrictSchemaModel):
    """Deterministic coverage matrix with closeability and backfill evidence."""

    project: Annotated[str, described_field("Evaluated project identity.")]
    timezone: Annotated[str, described_field("Timezone used for boundary math.")]
    start_date: Annotated[str, _ISO_DATE, described_field("Inclusive range start.")]
    end_date: Annotated[str, _ISO_DATE, described_field("Inclusive range end.")]
    matrix: Annotated[
        list[ObsidianTemporalCoverageRowResponse],
        described_field("Per-date coverage rows in ascending date order."),
    ]
    closable_daily: Annotated[
        list[str], described_field("Dates where every expected family is present.")
    ]
    open_daily: Annotated[
        list[str], described_field("Today and future dates that cannot be closed.")
    ]
    missing_expected_sources: Annotated[
        list[dict[str, str]],
        described_field("Expected family-days with no packet."),
    ]
    late_backfills: Annotated[
        list[dict[str, str | None]],
        described_field("Family-days whose packet was created after its target date."),
    ]
    weekly_close_due: Annotated[
        bool,
        described_field(
            "Whether a fully-ended ISO week inside the range is fully closable."
        ),
    ]
    monthly_close_due: Annotated[
        bool,
        described_field(
            "Whether a fully-ended calendar month inside the range is closable."
        ),
    ]
    unparsed_note_count: Annotated[
        int,
        described_field("Managed notes skipped because their source failed to parse."),
    ]
    boundary_policy: Annotated[
        dict[str, str],
        described_field("Explicit target, open-day, calendar and period boundaries."),
    ]
    source_evidence: Annotated[
        list[TemporalSourceEvidenceResponse],
        described_field(
            "Target date separate from actual ingestion time; unknown time is null."
        ),
    ]

    @classmethod
    def from_payload(
        cls, payload: TemporalCoveragePayload
    ) -> ObsidianTemporalCoverageResponse:
        """Build the response schema from the service payload."""
        rows = [
            ObsidianTemporalCoverageRowResponse(
                date=row["date"],
                iso_week=row["iso_week"],
                ordinal_week=row["ordinal_week"],
                families=row["families"],
            )
            for row in payload["matrix"]
        ]
        return cls(
            project=payload["project"],
            timezone=payload["timezone"],
            start_date=payload["start_date"],
            end_date=payload["end_date"],
            matrix=rows,
            closable_daily=payload["closable_daily"],
            open_daily=payload["open_daily"],
            missing_expected_sources=payload["missing_expected_sources"],
            late_backfills=payload["late_backfills"],
            weekly_close_due=payload["weekly_close_due"],
            monthly_close_due=payload["monthly_close_due"],
            unparsed_note_count=payload["unparsed_note_count"],
            boundary_policy=payload["boundary_policy"],
            source_evidence=[
                TemporalSourceEvidenceResponse(**evidence)
                for evidence in payload["source_evidence"]
            ],
        )
