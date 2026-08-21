"""Shared datetime schema contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp
from pydantic import ValidationError


class TimestampBoundary(StrictSchemaModel):
    """Tiny schema used to exercise shared timestamp validation."""

    timestamp: AwareTimestamp


def test_aware_timestamp_accepts_timezone_aware_iso_values() -> None:
    """Public datetime fields should accept timezone-aware ISO-8601 strings."""
    parsed = TimestampBoundary.model_validate_json(
        b'{"timestamp":"2026-05-20T10:30:00Z"}'
    )

    assert parsed.timestamp == datetime(2026, 5, 20, 10, 30, tzinfo=UTC)


def test_aware_timestamp_rejects_naive_iso_values() -> None:
    """Public datetime fields should reject values without timezone info."""
    with pytest.raises(ValidationError, match="timezone"):
        TimestampBoundary.model_validate_json(b'{"timestamp":"2026-05-20T10:30:00"}')


def test_aware_timestamp_rejects_numeric_epoch_values() -> None:
    """Public datetime fields should reject implicit epoch timestamps."""
    with pytest.raises(ValidationError, match="ISO-8601"):
        TimestampBoundary.model_validate_json(b'{"timestamp":123}')
