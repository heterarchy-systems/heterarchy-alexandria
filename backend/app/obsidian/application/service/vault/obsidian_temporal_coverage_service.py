"""Deterministic temporal coverage and late-backfill detection.

The Memory Steward previously discovered daily-packet coverage gaps by
repeated path searches. This service answers the same question in one
deterministic, LLM-free computation over the managed vault: which report
families are present, backfilled, missing, or not expected for each date in a
range, plus daily/weekly/monthly closeability.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date as calendar_date, datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anyio
import anyio.to_thread

from app.obsidian.domain.entities.obsidian_temporal_coverage import (
    TemporalCoveragePayload,
    TemporalCoverageRow,
    TemporalSourceEvidence,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
)
from app.obsidian.infrastructure.markdown.paths import (
    discover_managed_markdown_paths,
    resolve_note_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONValue

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEFAULT_TIMEZONE = "Asia/Seoul"


class ObsidianTemporalCoverageError(ObsidianValidationError):
    """Raised when a coverage request is not deterministically answerable."""


def _packet_family(frontmatter: Mapping[str, JSONValue]) -> str | None:
    """Return the report family of one parsed note, if any."""
    family = frontmatter.get("report_family") or frontmatter.get("report")
    return family if isinstance(family, str) and family else None


def _packet_date(frontmatter: Mapping[str, JSONValue]) -> calendar_date | None:
    """Return the target date of one parsed note, if any."""
    value = frontmatter.get("date")
    if not isinstance(value, str) or not _DATE_PATTERN.match(value):
        return None
    return calendar_date.fromisoformat(value)


def _created_time(
    frontmatter: Mapping[str, JSONValue], tz: ZoneInfo
) -> datetime | None:
    """Return the aware ingestion time of one parsed note, if any."""
    value = frontmatter.get("created_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed.astimezone(tz)


def _parse_iso_date(value: str, field: str) -> calendar_date:
    """Parse one strict ISO calendar date request field."""
    if not _DATE_PATTERN.match(value):
        raise ObsidianTemporalCoverageError(
            f"{field} must be an ISO calendar date: {value!r}"
        )
    return calendar_date.fromisoformat(value)


class ObsidianTemporalCoverageService:
    """Answer temporal coverage questions from durable vault packets."""

    def __init__(
        self,
        vault_config_store: ObsidianVaultConfigStore,
        today_provider: Callable[[], calendar_date] | None = None,
    ) -> None:
        """Initialize the read-only coverage boundary.

        Args:
            vault_config_store: Vault location authority.
            today_provider: Optional deterministic today override for tests;
                by default today is computed in the requested timezone.
        """
        self._vault_config_store = vault_config_store
        self._today_provider = today_provider

    async def coverage(
        self,
        *,
        project: str,
        start_date: str,
        end_date: str,
        families: tuple[str, ...] = (),
        not_expected: tuple[tuple[str, str], ...] = (),
        timezone: str = _DEFAULT_TIMEZONE,
    ) -> TemporalCoveragePayload:
        """Build one temporal coverage matrix.

        Args:
            project: Project identity whose packets are evaluated.
            start_date: Inclusive ISO range start.
            end_date: Inclusive ISO range end.
            families: Expected report families; when empty, only observed
                families are reported and nothing is MISSING.
            not_expected: (family, date) pairs that are NOT_EXPECTED rather
                than MISSING, such as market holidays.
            timezone: IANA timezone for today/open-day and week boundaries.

        Returns:
            JSON-compatible coverage matrix payload.

        Raises:
            ObsidianTemporalCoverageError: When the range or timezone is invalid.
        """
        return await anyio.to_thread.run_sync(
            partial(
                self._coverage_sync,
                project=project,
                start_date=start_date,
                end_date=end_date,
                families=families,
                not_expected=not_expected,
                timezone=timezone,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    def _coverage_sync(
        self,
        *,
        project: str,
        start_date: str,
        end_date: str,
        families: tuple[str, ...],
        not_expected: tuple[tuple[str, str], ...],
        timezone: str,
    ) -> TemporalCoveragePayload:
        """Execute the vault scan and deterministic classification."""
        range_start = _parse_iso_date(start_date, "start_date")
        range_end = _parse_iso_date(end_date, "end_date")
        if range_end < range_start:
            raise ObsidianTemporalCoverageError("end_date must not precede start_date")
        if (range_end - range_start).days >= 366:
            raise ObsidianTemporalCoverageError(
                "coverage range must be at most 366 days"
            )
        if len(families) > 50 or len(not_expected) > 18300:
            raise ObsidianTemporalCoverageError(
                "coverage supports at most 50 families and 18300 exclusions"
            )
        try:
            tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ObsidianTemporalCoverageError(
                f"unknown timezone: {timezone!r}"
            ) from exc
        today = (
            self._today_provider()
            if self._today_provider is not None
            else datetime.now(tz).date()
        )
        packets, source_evidence, unparsed = self._scan_packets(project=project, tz=tz)
        expected_families = tuple(families) or tuple(sorted({p[0] for p in packets}))
        not_expected_set = {
            (family, _parse_iso_date(day, "not_expected date"))
            for family, day in not_expected
        }

        matrix: list[TemporalCoverageRow] = []
        closable: list[str] = []
        open_days: list[str] = []
        missing: list[dict[str, str]] = []
        backfills: list[dict[str, str | None]] = []
        cursor = range_start
        while cursor <= range_end:
            iso, ordinal = _week_labels(cursor)
            row: TemporalCoverageRow = {
                "date": cursor.isoformat(),
                "iso_week": iso,
                "ordinal_week": ordinal,
                "families": {},
            }
            row_closable = True
            is_open = cursor >= today
            for family in expected_families:
                created = packets.get((family, cursor))
                if is_open:
                    state = "OPEN"
                elif (family, cursor) in not_expected_set:
                    state = "NOT_EXPECTED"
                elif created is None:
                    state = "MISSING"
                elif created > cursor:
                    state = "BACKFILL"
                else:
                    state = "COMPLETE"
                if state not in {"COMPLETE", "BACKFILL", "NOT_EXPECTED"}:
                    row_closable = False
                if state == "MISSING":
                    missing.append({"date": cursor.isoformat(), "family": family})
                if state == "BACKFILL":
                    backfills.append(
                        {
                            "date": cursor.isoformat(),
                            "family": family,
                            "created_date": created.isoformat()
                            if created is not None
                            else None,
                        }
                    )
                row["families"][family] = state
            iso, ordinal = _week_labels(cursor)
            row["iso_week"] = iso
            row["ordinal_week"] = ordinal
            matrix.append(row)
            if is_open:
                open_days.append(cursor.isoformat())
            elif row_closable and expected_families:
                closable.append(cursor.isoformat())
            cursor += timedelta(days=1)

        expected_set = set(expected_families)
        return {
            "project": project,
            "timezone": timezone,
            "start_date": range_start.isoformat(),
            "end_date": range_end.isoformat(),
            "matrix": matrix,
            "closable_daily": closable,
            "open_daily": open_days,
            "missing_expected_sources": missing,
            "late_backfills": backfills,
            "weekly_close_due": _weekly_close_due(
                range_start, range_end, today, expected_set, packets, not_expected_set
            ),
            "monthly_close_due": _monthly_close_due(
                range_start, range_end, today, expected_set, packets, not_expected_set
            ),
            "unparsed_note_count": unparsed,
            "boundary_policy": {
                "target_date": "source_date_in_requested_timezone",
                "open_day": "today_and_future",
                "iso_week": "monday_through_sunday",
                "ordinal_week": "month_day_groups_of_seven",
                "calendar_exclusions": "caller_declared",
                "complete": "durable_packet_presence_not_contemporaneous_observation",
            },
            "source_evidence": [
                evidence
                for (family, day), evidence in sorted(source_evidence.items())
                if family in expected_set and range_start <= day <= range_end
            ],
        }

    def _scan_packets(
        self,
        *,
        project: str,
        tz: ZoneInfo,
    ) -> tuple[
        dict[tuple[str, calendar_date], calendar_date],
        dict[tuple[str, calendar_date], TemporalSourceEvidence],
        int,
    ]:
        """Scan managed markdown into (family, date) -> created-date packets."""
        config = self._vault_config_store.current()
        root = resolve_note_path(config.vault_path, config.alexandria_root)
        packets: dict[tuple[str, calendar_date], calendar_date] = {}
        evidence: dict[tuple[str, calendar_date], TemporalSourceEvidence] = {}
        unparsed = 0
        if not root.is_dir():
            return packets, evidence, unparsed
        for path in discover_managed_markdown_paths(root):
            try:
                text = path.read_text(encoding="utf-8")
                document = parse_markdown_document(text)
            except (OSError, UnicodeError, ValueError):
                unparsed += 1
                continue
            frontmatter = frontmatter_json(document.frontmatter)
            note_project = frontmatter.get("project")
            if note_project != project:
                continue
            family = _packet_family(frontmatter)
            try:
                packet_date = _packet_date(frontmatter)
            except ValueError:
                unparsed += 1
                continue
            if family is None or packet_date is None:
                continue
            # Unknown ingestion time proves presence only; expose null rather
            # than synthesizing contemporaneous observation from the target.
            created_time = _created_time(frontmatter, tz)
            created = created_time.date() if created_time is not None else None
            key = (family, packet_date)
            existing = evidence.get(key)
            if existing is None or (
                created is not None
                and (
                    existing["ingestion_date"] is None
                    or created.isoformat() < existing["ingestion_date"]
                )
            ):
                packets[key] = created or packet_date
                evidence[key] = {
                    "family": family,
                    "target_date": packet_date.isoformat(),
                    "source_created_at": created_time.isoformat()
                    if created_time is not None
                    else None,
                    "ingestion_date": created.isoformat()
                    if created is not None
                    else None,
                }
        return packets, evidence, unparsed


def _week_labels(value: calendar_date) -> tuple[str, str]:
    """Return the ISO week and month-ordinal week labels for one date."""
    iso_year, iso_week, _ = value.isocalendar()
    ordinal_week = (value.day - 1) // 7 + 1
    return f"{iso_year}-W{iso_week:02d}", f"{value:%Y-%m}-W{ordinal_week}"


def _week_is_closable(
    week_start: calendar_date,
    range_start: calendar_date,
    range_end: calendar_date,
    today: calendar_date,
    expected: set[str],
    packets: dict[tuple[str, calendar_date], calendar_date],
    not_expected: set[tuple[str, calendar_date]],
) -> bool:
    """Return whether one Mon-Sun week is fully past, in range, and closable."""
    week_end = week_start + timedelta(days=6)
    if week_start < range_start or week_end > range_end or week_end >= today:
        return False
    cursor = week_start
    while cursor <= week_end:
        for family in expected:
            created = packets.get((family, cursor))
            if created is None and (family, cursor) not in not_expected:
                return False
        cursor += timedelta(days=1)
    return True


def _weekly_close_due(
    range_start: calendar_date,
    range_end: calendar_date,
    today: calendar_date,
    expected: set[str],
    packets: dict[tuple[str, calendar_date], calendar_date],
    not_expected: set[tuple[str, calendar_date]],
) -> bool:
    """Return whether a fully-ended ISO week inside the range is closable."""
    if not expected:
        return False
    # Walk the Mondays of the range.
    cursor = range_start
    while cursor.weekday() != 0:
        cursor += timedelta(days=1)
    while cursor <= range_end:
        if _week_is_closable(
            cursor, range_start, range_end, today, expected, packets, not_expected
        ):
            return True
        cursor += timedelta(days=7)
    return False


def _monthly_close_due(
    range_start: calendar_date,
    range_end: calendar_date,
    today: calendar_date,
    expected: set[str],
    packets: dict[tuple[str, calendar_date], calendar_date],
    not_expected: set[tuple[str, calendar_date]],
) -> bool:
    """Return whether a fully-ended calendar month inside the range is closable."""
    if not expected:
        return False
    month_start = range_start.replace(day=1)
    while month_start <= range_end:
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        if (
            month_start >= range_start
            and month_end <= range_end
            and month_end < today
            and _span_closable(month_start, month_end, expected, packets, not_expected)
        ):
            return True
        month_start = next_month
    return False


def _span_closable(
    span_start: calendar_date,
    span_end: calendar_date,
    expected: set[str],
    packets: dict[tuple[str, calendar_date], calendar_date],
    not_expected: set[tuple[str, calendar_date]],
) -> bool:
    """Return whether every expected family-day in one span is present."""
    cursor = span_start
    while cursor <= span_end:
        for family in expected:
            if (
                packets.get((family, cursor)) is None
                and (
                    family,
                    cursor,
                )
                not in not_expected
            ):
                return False
        cursor += timedelta(days=1)
    return True
