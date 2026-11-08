"""Async access to legacy report-bundle checkpoint records."""

from __future__ import annotations

from functools import partial
from typing import TypedDict

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianReportBundleResult
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.types.extra_types import JSONObject, JSONValue


class ReportBundleOwnerWriteCheckpointDict(TypedDict):
    """Legacy owner-write reference stored in report-bundle checkpoints."""

    note_id: str
    operation: str


class ReportBundleCheckpointDict(TypedDict):
    """The ten-key legacy report-bundle checkpoint wire record."""

    request_hash: str
    completion_status: str
    failed_stage: str | None
    source_note_id: str | None
    expected_incoming_edges: int
    verified_incoming_edges: int
    unresolved_links: list[str]
    duplicates: list[str]
    errors: list[JSONObject]
    owner_writes: list[JSONObject]


class ReportBundleCheckpoints:
    """Keep synchronous checkpoint filesystem I/O off the event loop."""

    async def load(
        self,
        store: ObsidianReportBundleRunStore,
        idempotency_key: str,
    ) -> JSONObject | None:
        """Load one checkpoint through the existing owned sync bridge.

        Args:
            store: Existing report-bundle run store.
            idempotency_key: Original unprefixed idempotency key.

        Returns:
            The legacy checkpoint record, or None when it does not exist.
        """
        return await run_critical_sync(
            partial(store.load, idempotency_key=idempotency_key)
        )

    async def save(
        self,
        store: ObsidianReportBundleRunStore,
        request: ObsidianReportBundleRequest,
        request_hash: str,
        result: ObsidianReportBundleResult,
    ) -> None:
        """Save one checkpoint through the existing owned sync bridge.

        Args:
            store: Existing report-bundle run store.
            request: Normalized request carrying the original key.
            request_hash: Canonical request hash used for idempotency checks.
            result: Operation result to persist in legacy wire form.
        """
        checkpoint = ReportBundleCheckpointDict(
            request_hash=request_hash,
            completion_status=result.completion_status.value,
            failed_stage=result.failed_stage,
            source_note_id=(
                None if result.source is None else result.source.note.note_id
            ),
            expected_incoming_edges=result.graph.expected_incoming_edges,
            verified_incoming_edges=result.graph.verified_incoming_edges,
            unresolved_links=list(result.graph.unresolved_links),
            duplicates=list(result.duplicates),
            errors=list(result.errors),
            owner_writes=[
                dict[str, JSONValue](
                    **ReportBundleOwnerWriteCheckpointDict(
                        note_id=item.note.note_id,
                        operation=item.operation.value,
                    )
                )
                for item in result.owner_writes
            ],
        )
        record: JSONObject = dict[str, JSONValue](**checkpoint)
        await run_critical_sync(
            partial(
                store.save,
                idempotency_key=request.idempotency_key,
                record=record,
            )
        )


def _checkpoint_int(checkpoint: JSONObject, key: str) -> int:
    """Read one legacy integer field while rejecting booleans.

    Args:
        checkpoint: Existing JSON checkpoint record.
        key: Integer field to read.

    Returns:
        The stored integer or zero for missing and invalid values.
    """
    value = checkpoint.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _checkpoint_string(checkpoint: JSONObject, key: str) -> str | None:
    """Read one optional legacy string field.

    Args:
        checkpoint: Existing JSON checkpoint record.
        key: String field to read.

    Returns:
        The stored string or None for missing and invalid values.
    """
    value = checkpoint.get(key)
    return value if isinstance(value, str) else None


def _checkpoint_strings(checkpoint: JSONObject, key: str) -> list[str]:
    """Read valid strings from one legacy list field, preserving order.

    Args:
        checkpoint: Existing JSON checkpoint record.
        key: String-list field to read.

    Returns:
        Stored strings in their original order, or an empty list.
    """
    value = checkpoint.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _checkpoint_dicts(checkpoint: JSONObject, key: str) -> list[JSONObject]:
    """Read mapping items from one legacy list field without changing order.

    Args:
        checkpoint: Existing JSON checkpoint record.
        key: Mapping-list field to read.

    Returns:
        Stored JSON mappings in their original order, or an empty list.
    """
    value = checkpoint.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
