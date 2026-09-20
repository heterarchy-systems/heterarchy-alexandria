"""Bounded batch note service contracts: partial success and CAS conflict."""

from __future__ import annotations

from types import SimpleNamespace

import anyio
import pytest

from app.obsidian.application.service.notes.obsidian_batch_note_service import (
    ObsidianBatchNoteService,
)
from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchReadSelector,
    BatchWriteOperation,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)


def test_batch_write_operation_from_payload_validates_shape() -> None:
    """JSON payloads parse into operations and reject invalid shapes."""
    operation = BatchWriteOperation.from_payload(
        {
            "op": "update",
            "title": "T",
            "body": "b",
            "relative_path": "Alexandria/T.md",
            "expected_content_hash": "h",
            "frontmatter": {"scope": "GLOBAL"},
        }
    )
    assert operation.expected_content_hash == "h"
    assert operation.frontmatter == {"scope": "GLOBAL"}

    with pytest.raises(ValueError, match="BATCH_OPERATION_INVALID"):
        BatchWriteOperation.from_payload({"op": "update"})
    with pytest.raises(ValueError, match="BATCH_OPERATION_INVALID"):
        BatchWriteOperation.from_payload("not-an-object")


class _FakeObsidianService:
    """CAS write authority double: one conflicting path, one writable path."""

    async def write_note(self, command: object) -> object:
        save = command.note
        if save.expected_content_hash == "stale-hash":
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: expected content hash does not match "
                f"the current note: {save.relative_path}",
                current_content_hash="fresh-hash",
            )
        return SimpleNamespace(
            operation=SimpleNamespace(value="UPDATED"),
            note=SimpleNamespace(content_hash="written-hash"),
        )

    async def read_note_by_path(self, path: str) -> object:
        if "Broken" in path:
            raise ObsidianValidationError("FRONTMATTER_PARSE_ERROR: broken")
        raise ObsidianNotFoundError(f"note not found: {path}")


def test_batch_read_reports_parse_error_without_failing_the_batch() -> None:
    """A malformed note becomes a per-item parse_error, not a batch failure."""
    service = ObsidianBatchNoteService(
        obsidian_service=_FakeObsidianService(),  # type: ignore[arg-type]
        diagnostics_service=SimpleNamespace(),  # type: ignore[arg-type]
    )

    result = anyio.run(
        service.batch_read,
        [
            BatchReadSelector(path="Alexandria/Broken.md"),
            BatchReadSelector(path="Alexandria/Missing.md"),
        ],
    )

    assert [item.status for item in result.items] == ["parse_error", "not_found"]
    assert result.items[0].parse_error is not None
    assert "FRONTMATTER_PARSE_ERROR" in result.items[0].parse_error


def test_batch_write_reports_conflict_with_current_cas_evidence() -> None:
    """A conflicted item must carry the current hash for one-shot retry."""
    service = ObsidianBatchNoteService(
        obsidian_service=_FakeObsidianService(),  # type: ignore[arg-type]
        diagnostics_service=SimpleNamespace(),  # type: ignore[arg-type]
    )
    operations = [
        BatchWriteOperation(
            op="update",
            title="Conflicted",
            body="stale body",
            relative_path="Alexandria/Conflicted.md",
            expected_content_hash="stale-hash",
        ),
        BatchWriteOperation(
            op="update",
            title="Writable",
            body="fresh body",
            relative_path="Alexandria/Writable.md",
            expected_content_hash="good-hash",
        ),
    ]

    result = anyio.run(service.batch_write, operations)

    assert [item.status for item in result.items] == ["conflict", "updated"]
    assert result.items[0].current_content_hash == "fresh-hash"
    assert result.items[0].content_hash is None
    assert result.items[1].content_hash == "written-hash"
    assert result.succeeded == 1
    assert result.conflicted == 1


def test_batch_read_reports_not_found_independently() -> None:
    """One missing note must not fail the remaining batch items."""
    service = ObsidianBatchNoteService(
        obsidian_service=_FakeObsidianService(),  # type: ignore[arg-type]
        diagnostics_service=SimpleNamespace(),  # type: ignore[arg-type]
    )

    result = anyio.run(
        service.batch_read,
        [BatchReadSelector(path="Alexandria/Missing.md")],
    )

    assert [item.status for item in result.items] == ["not_found"]
