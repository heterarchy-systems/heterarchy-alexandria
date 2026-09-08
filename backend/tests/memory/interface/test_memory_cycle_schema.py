"""Boundary tests for the project-scoped Memory-cycle request contract."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_schema import (
    MemoryCycleRequestSchema,
)


def test_memory_cycle_schema_requires_project_and_defaults_project_scope() -> None:
    """The high-level composite cannot silently broaden Compact authority."""
    adapter = TypeAdapter(MemoryCycleRequestSchema)
    request = adapter.validate_json(
        b'{"operation":"dry_run","project":"real-cycle",'
        b'"window_start":"2026-09-08T00:00:00Z",'
        b'"window_end":"2026-09-08T01:00:00Z",'
        b'"idempotency_key":"schema-test"}'
    )
    assert request.scope == "PROJECT"

    with pytest.raises(ValidationError):
        adapter.validate_json(
            b'{"operation":"dry_run","window_start":"2026-09-08T00:00:00Z",'
            b'"window_end":"2026-09-08T01:00:00Z",'
            b'"idempotency_key":"missing-project"}'
        )
    with pytest.raises(ValidationError):
        adapter.validate_json(
            b'{"operation":"dry_run","project":"real-cycle","scope":"AGENT",'
            b'"window_start":"2026-09-08T00:00:00Z",'
            b'"window_end":"2026-09-08T01:00:00Z",'
            b'"idempotency_key":"agent-scope"}'
        )
