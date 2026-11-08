"""Strict JSON-mode tool argument validation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import pytest
from pydantic import TypeAdapter, ValidationError

from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.type_validation.strict_json_arg import json_mode_arg


class SampleModel(StrictSchemaModel):
    """Sample strict schema used to verify json_mode_arg behavior."""

    count: int
    score: float
    timestamp: AwareTimestamp


class OtherModel(StrictSchemaModel):
    """Unrelated strict schema used to verify model-type rejection."""

    label: str


_SAMPLE_ARG_ADAPTER = TypeAdapter(
    Annotated[SampleModel, json_mode_arg(SampleModel)],
)


def test_json_mode_arg_passes_through_validated_model_instance() -> None:
    """Already-validated BaseModel instances pass through without re-encoding."""
    existing = SampleModel(
        count=3,
        score=1.5,
        timestamp=datetime(2026, 5, 20, 10, 30, tzinfo=UTC),
    )

    validated = _SAMPLE_ARG_ADAPTER.validate_python(existing)

    assert validated is existing


def test_json_mode_arg_rejects_different_base_model_subclass() -> None:
    """Passing a different BaseModel subclass still fails target schema validation."""
    wrong_model = OtherModel(label="wrong")

    with pytest.raises(ValidationError):
        _SAMPLE_ARG_ADAPTER.validate_python(wrong_model)


def test_json_mode_arg_validates_json_compatible_mapping() -> None:
    """Framework-decoded mappings with JSON primitives validate in JSON mode."""
    validated = _SAMPLE_ARG_ADAPTER.validate_python(
        {
            "count": 3,
            "score": 1.5,
            "timestamp": "2026-05-20T10:30:00Z",
        },
    )

    assert validated == SampleModel(
        count=3,
        score=1.5,
        timestamp=datetime(2026, 5, 20, 10, 30, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "count": 1,
            "score": 1.0,
            "timestamp": datetime(2026, 5, 20, 10, 30, tzinfo=UTC),
        },
        {
            "count": 1 << 64,
            "score": 1.0,
            "timestamp": "2026-05-20T10:30:00Z",
        },
        {
            "count": 1,
            "score": float("nan"),
            "timestamp": "2026-05-20T10:30:00Z",
        },
    ],
)
def test_json_mode_arg_converts_non_json_values_into_validation_error(
    invalid_payload: dict[str, object],
) -> None:
    """Non-JSON Python values raise ValidationError instead of uncaught TypeError."""
    with pytest.raises(
        ValidationError,
        match="argument must contain JSON-compatible values",
    ):
        _SAMPLE_ARG_ADAPTER.validate_python(invalid_payload)
