"""Deterministic temporal coverage service tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import anyio
import pytest

from app.obsidian.application.service.vault.obsidian_temporal_coverage_service import (
    ObsidianTemporalCoverageError,
    ObsidianTemporalCoverageService,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)


def _packet(
    path: Path,
    *,
    family: str,
    packet_date: str,
    created_at: str,
    project: str = "crypto-intel",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: ctx_{family}_{packet_date}\n"
        "alexandria_type: context\n"
        f"project: {project}\n"
        f"report_family: {family}\n"
        f"date: {packet_date}\n"
        f"created_at: {created_at}\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )


def _service(tmp_path: Path, today: date) -> ObsidianTemporalCoverageService:
    store = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path / "vault"),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    return ObsidianTemporalCoverageService(store, today_provider=lambda: today)


def test_backfill_missing_open_and_not_expected_states(tmp_path: Path) -> None:
    """BACKFILL, MISSING, OPEN, and NOT_EXPECTED are classified deterministically."""

    async def scenario() -> dict:
        vault = tmp_path / "vault" / "Alexandria"
        _packet(
            vault / "crypto" / "2026-09-27.md",
            family="crypto",
            packet_date="2026-09-27",
            created_at="2026-09-28T09:00:00+09:00",
        )
        _packet(
            vault / "macro" / "2026-09-27.md",
            family="macro",
            packet_date="2026-09-27",
            created_at="2026-09-27T08:00:00+09:00",
        )
        service = _service(tmp_path, today=date(2026, 9, 30))
        return await service.coverage(
            project="crypto-intel",
            start_date="2026-09-26",
            end_date="2026-09-30",
            families=("crypto", "macro"),
            not_expected=(
                ("crypto", "2026-09-26"),
                ("macro", "2026-09-26"),
            ),
        )

    payload = anyio.run(scenario)

    by_date = {row["date"]: row for row in payload["matrix"]}
    assert by_date["2026-09-26"]["families"] == {
        "crypto": "NOT_EXPECTED",
        "macro": "NOT_EXPECTED",
    }
    assert by_date["2026-09-27"]["families"]["crypto"] == "BACKFILL"
    assert by_date["2026-09-27"]["families"]["macro"] == "COMPLETE"
    assert by_date["2026-09-28"]["families"]["crypto"] == "MISSING"
    assert by_date["2026-09-30"]["families"]["macro"] == "OPEN"
    assert payload["open_daily"] == ["2026-09-30"]
    assert {"date": "2026-09-27", "family": "crypto", "created_date": "2026-09-28"} in (
        payload["late_backfills"]
    )
    assert {"date": "2026-09-28", "family": "crypto"} in (
        payload["missing_expected_sources"]
    )
    assert payload["closable_daily"] == ["2026-09-26", "2026-09-27"]


def test_weekly_close_due_requires_complete_iso_week_before_today(
    tmp_path: Path,
) -> None:
    """A fully-ended Mon-Sun week inside the range is due when fully present."""

    async def scenario() -> tuple[bool, bool]:
        vault = tmp_path / "vault" / "Alexandria"
        for day in range(21, 28):
            packet_date = f"2026-09-{day:02d}"
            _packet(
                vault / f"crypto-{packet_date}.md",
                family="crypto",
                packet_date=packet_date,
                created_at=f"2026-09-{day:02d}T21:00:00+09:00",
            )
        service = _service(tmp_path, today=date(2026, 9, 30))
        complete = await service.coverage(
            project="crypto-intel",
            start_date="2026-09-21",
            end_date="2026-09-27",
            families=("crypto",),
        )
        (vault / "crypto-2026-09-25.md").unlink()
        gapped = await service.coverage(
            project="crypto-intel",
            start_date="2026-09-21",
            end_date="2026-09-27",
            families=("crypto",),
        )
        return complete["weekly_close_due"], gapped["weekly_close_due"]

    complete_due, gapped_due = anyio.run(scenario)

    assert complete_due is True
    assert gapped_due is False


def test_iso_and_ordinal_week_labels_are_both_explicit(tmp_path: Path) -> None:
    """Each matrix row carries both ISO-week and month-ordinal labels."""

    async def scenario() -> dict:
        service = _service(tmp_path, today=date(2026, 9, 30))
        return await service.coverage(
            project="crypto-intel",
            start_date="2026-09-01",
            end_date="2026-09-01",
        )

    payload = anyio.run(scenario)

    row = payload["matrix"][0]
    assert row["iso_week"] == "2026-W36"
    assert row["ordinal_week"] == "2026-09-W1"


def test_invalid_range_and_timezone_fail_closed(tmp_path: Path) -> None:
    """Invalid ranges and unknown timezones are rejected deterministically."""

    async def scenario() -> tuple[str, str]:
        service = _service(tmp_path, today=date(2026, 9, 30))
        try:
            await service.coverage(
                project="p", start_date="2026-09-10", end_date="2026-09-01"
            )
        except ObsidianTemporalCoverageError as exc:
            range_error = str(exc)
        try:
            await service.coverage(
                project="p",
                start_date="2026-09-01",
                end_date="2026-09-02",
                timezone="Mars/Olympus",
            )
        except ObsidianTemporalCoverageError as exc:
            tz_error = str(exc)
        return range_error, tz_error

    range_error, tz_error = anyio.run(scenario)

    assert "end_date" in range_error
    assert "Mars/Olympus" in tz_error


def test_unexpected_projects_and_unparseable_notes_are_excluded(
    tmp_path: Path,
) -> None:
    """Foreign-project packets never fill expected families; parse failures count."""

    async def scenario() -> dict:
        vault = tmp_path / "vault" / "Alexandria"
        _packet(
            vault / "other.md",
            family="crypto",
            packet_date="2026-09-01",
            created_at="2026-09-01T09:00:00+09:00",
            project="other-project",
        )
        broken = vault / "broken.md"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("---\nid: broken\n", encoding="utf-8")
        service = _service(tmp_path, today=date(2026, 9, 30))
        return await service.coverage(
            project="crypto-intel",
            start_date="2026-09-01",
            end_date="2026-09-01",
            families=("crypto",),
        )

    payload = anyio.run(scenario)

    assert payload["matrix"][0]["families"]["crypto"] == "MISSING"
    assert payload["unparsed_note_count"] == 1


def test_future_packets_and_empty_families_cannot_close_periods(tmp_path: Path) -> None:
    """Only ended periods with an explicit source family can be closed."""

    async def scenario():
        _packet(
            tmp_path / "vault" / "Alexandria" / "future.md",
            family="crypto",
            packet_date="2026-10-01",
            created_at="2026-09-30T09:00:00+09:00",
        )
        service = _service(tmp_path, today=date(2026, 9, 30))
        future = await service.coverage(
            project="crypto-intel",
            start_date="2026-10-01",
            end_date="2026-10-01",
            families=("crypto",),
        )
        empty = await service.coverage(
            project="no-packets",
            start_date="2026-08-01",
            end_date="2026-08-31",
        )
        return future, empty

    future, empty = anyio.run(scenario)
    assert future["closable_daily"] == []
    assert future["matrix"][0]["families"]["crypto"] == "OPEN"
    assert empty["weekly_close_due"] is empty["monthly_close_due"] is False


def test_invalid_packet_date_is_reported_and_request_range_is_bounded(
    tmp_path: Path,
) -> None:
    """Malformed source dates stay visible and cannot abort other coverage evidence."""

    async def scenario():
        _packet(
            tmp_path / "vault" / "Alexandria" / "bad-date.md",
            family="crypto",
            packet_date="2026-09-99",
            created_at="2026-09-30T09:00:00+09:00",
        )
        service = _service(tmp_path, today=date(2026, 9, 30))
        payload = await service.coverage(
            project="crypto-intel",
            start_date="2026-09-01",
            end_date="2026-09-30",
            families=("crypto",),
        )
        with pytest.raises(ObsidianTemporalCoverageError, match="366"):
            await service.coverage(
                project="crypto-intel", start_date="2000-01-01", end_date="2026-09-30"
            )
        return payload

    payload = anyio.run(scenario)
    assert payload["unparsed_note_count"] == 1


def test_calendar_exclusion_is_explicit_and_ingestion_evidence_is_separate(
    tmp_path: Path,
) -> None:
    """Caller calendar policy never fabricates packet or observation time."""

    async def scenario():
        vault = tmp_path / "vault" / "Alexandria"
        _packet(
            vault / "stock.md",
            family="stock_close",
            packet_date="2026-09-24",
            created_at="2026-09-25T00:30:00+09:00",
        )
        _packet(
            vault / "unknown.md",
            family="crypto",
            packet_date="2026-09-24",
            created_at="unavailable",
        )
        return await _service(tmp_path, today=date(2026, 9, 30)).coverage(
            project="crypto-intel",
            start_date="2026-09-24",
            end_date="2026-09-25",
            families=("stock_close", "crypto"),
            not_expected=(("stock_close", "2026-09-25"),),
        )

    payload = anyio.run(scenario)
    assert payload["matrix"][1]["families"] == {
        "stock_close": "NOT_EXPECTED",
        "crypto": "MISSING",
    }
    assert payload["boundary_policy"]["calendar_exclusions"] == "caller_declared"
    evidence = {row["family"]: row for row in payload["source_evidence"]}
    assert evidence["stock_close"]["target_date"] == "2026-09-24"
    assert evidence["stock_close"]["source_created_at"] == "2026-09-25T00:30:00+09:00"
    assert evidence["crypto"]["source_created_at"] is None
    assert evidence["crypto"]["ingestion_date"] is None
