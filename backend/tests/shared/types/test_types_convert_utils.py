"""Tests for shared interface payload conversion helpers."""

from __future__ import annotations

from enum import StrEnum

import pytest

from app.shared.exceptions.common_exceptions import BoundaryValidationError
from app.shared.types.types_convert_utils import (
    enum_value,
)


class ExampleSource(StrEnum):
    """Example string enum for conversion tests."""

    MANUAL = "manual"
    AGENT = "agent"


def test_enum_value_accepts_typed_enum_or_enum_string() -> None:
    """Return a typed enum from either enum instances or valid string values."""
    assert (
        enum_value(ExampleSource.MANUAL, ExampleSource, "source")
        is ExampleSource.MANUAL
    )
    assert enum_value("agent", ExampleSource, "source") is ExampleSource.AGENT

    with pytest.raises(BoundaryValidationError):
        enum_value("unknown", ExampleSource, "source")
