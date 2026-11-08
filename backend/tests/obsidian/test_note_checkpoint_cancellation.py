"""Cancellation must retain writer ownership through durable checkpoint writes."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest
from pydantic import TypeAdapter

from app.obsidian.application.notes.mutations.receipt_identity import (
    ReceiptIdentityPolicy,
)
from app.obsidian.application.notes.mutations.receipts import (
    NoteMutationReceipts,
)
from app.obsidian.application.notes.relations.checkpoints import save_checkpoint
from app.obsidian.application.notes.verified_upsert.obsidian_verified_upsert_policy import (
    verified_upsert_request_hash,
)
from app.obsidian.application.notes.verified_upsert.obsidian_verified_upsert_service import (
    ObsidianVerifiedUpsertService,
)
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
    ObsidianVerifiedUpsertCheckpoint,
    ObsidianVerifiedUpsertRequest,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    NoteMutationReceipt,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianCanonicalIdentityResult,
    ObsidianNote,
    ObsidianNoteWriteResult,
)
from app.obsidian.domain.entities.obsidian_relation import (
    ObsidianRelateCheckpoint,
    ObsidianRelateResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
    ObsidianRelationType,
    ObsidianWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIdempotencyConflictError,
    ObsidianNotFoundError,
)

type CheckpointRecord = ObsidianRelateCheckpoint | NoteMutationReceipt


def _request(*, body: str, key: str) -> ObsidianVerifiedUpsertRequest:
    """Build one actual verified-upsert command."""
    return ObsidianVerifiedUpsertRequest(
        identity=ObsidianLogicalIdentity(
            project="Project",
            report="Morning Read",
            date="2026-11-07",
            entity="ETH",
        ),
        title="ETH Morning Read",
        body=body,
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        idempotency_key=key,
    )


class _UpsertPorts:
    """Only the remote/index ports are faked; note files remain temporary and real."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.note: ObsidianNote | None = None
        self.resolutions = 0
        self.writes = 0

    async def resolve_logical_identity(
        self, identity: ObsidianLogicalIdentity
    ) -> ObsidianCanonicalIdentityResult:
        self.resolutions += 1
        return ObsidianCanonicalIdentityResult(
            canonical_report_family="Report",
            canonical_entity="ETH",
            canonical_path="Alexandria/test.md",
            existing_note_id=None if self.note is None else self.note.note_id,
            aliases=(),
            resolution=(
                "NEW_CANONICAL_IDENTITY"
                if self.note is None
                else "EXISTING_CANONICAL_FAMILY"
            ),
        )

    async def read_note_by_path(self, path: str) -> ObsidianNote:
        if self.note is None:
            raise ObsidianNotFoundError(path)
        return self.note

    async def read_note(self, note_id: str) -> ObsidianNote:
        if self.note is None:
            raise ObsidianNotFoundError(note_id)
        return self.note

    async def write_note(self, command: object) -> ObsidianNoteWriteResult:
        note_command = command.note  # type: ignore[attr-defined]
        destination = self.root / note_command.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(note_command.body)
        self.writes += 1
        self.note = ObsidianNote(
            note_id="test",
            relative_path=note_command.relative_path,
            alexandria_type=note_command.alexandria_type,
            title=note_command.title,
            status="active",
            tags=note_command.tags,
            project=note_command.project,
            source=note_command.source,
            content_hash=hash_text(note_command.body),
            frontmatter=note_command.frontmatter,
            body=note_command.body,
            index_status=ObsidianIndexStatus.INDEXED,
            error_message=None,
            size_bytes=len(note_command.body.encode()),
            modified_at=datetime.now(UTC),
            indexed_at=None,
        )
        return ObsidianNoteWriteResult(
            operation=ObsidianWriteOperation.CREATED,
            write_mode=command.write_mode,  # type: ignore[attr-defined]
            match_by=command.match_by,  # type: ignore[attr-defined]
            note=self.note,
            storage_status="stored",
            metadata_status="indexed",
            fts_status="indexed",
            graph_edge_index_status="indexed",
            graph_projection_status="stale",
            reindex_required=True,
        )


async def _next_loop_turn() -> None:
    """Let queued cancellation callbacks run without a wall-clock sleep."""
    ready = asyncio.Event()
    asyncio.get_running_loop().call_soon(ready.set)
    await asyncio.wait_for(ready.wait(), timeout=3)


def _replace_gate(
    loop: asyncio.AbstractEventLoop,
) -> tuple[asyncio.Event, threading.Event, asyncio.Event, Callable[[Path, Path], None]]:
    entered = asyncio.Event()
    release = threading.Event()
    replaced = asyncio.Event()
    real_replace = os.replace
    first_replace = True

    def gated_replace(source: Path, destination: Path) -> None:
        nonlocal first_replace
        if first_replace:
            first_replace = False
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError("test did not release the gated checkpoint write")
            try:
                real_replace(source, destination)
            finally:
                loop.call_soon_threadsafe(replaced.set)
            return
        real_replace(source, destination)

    return entered, release, replaced, gated_replace


async def _drain_gate_and_tasks(
    *,
    entered: asyncio.Event,
    release: threading.Event,
    replaced: asyncio.Event,
    tasks: list[asyncio.Task[object]],
) -> None:
    """Release blocked filesystem work and retrieve all task/thread outcomes."""
    release.set()
    if entered.is_set():
        await asyncio.wait_for(replaced.wait(), timeout=5)
        await anyio.to_thread.run_sync(lambda: None)
    if tasks:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=8
        )


def test_public_upsert_retains_writer_lease_through_cancelled_intent_save(
    tmp_path: Path,
) -> None:
    """A cancelled public upsert cannot let a same-key caller pass its intent save."""

    async def scenario() -> None:
        coordinator = IndexMaintenanceCoordinator()
        ports = _UpsertPorts(tmp_path)
        config = ObsidianVaultConfigStore(
            default_vault_path=str(tmp_path),
            default_alexandria_root="Alexandria",
            config_path=None,
        )

        async def noop() -> None:
            return None

        service = ObsidianVerifiedUpsertService(
            ports,
            ports,
            config,
            coordinator,
            noop,
            noop,
        )
        first_request = _request(body="first body", key="cancelled-public-upsert")
        retry_request = _request(body="second body", key="cancelled-public-upsert")
        loop = asyncio.get_running_loop()
        entered, release, replaced, gated_replace = _replace_gate(loop)
        tasks: list[asyncio.Task[object]] = []
        checkpoint_key = "verified-upsert:cancelled-public-upsert"
        checkpoint_store = ObsidianReportBundleRunStore(tmp_path)
        checkpoint_adapter = TypeAdapter(ObsidianVerifiedUpsertCheckpoint)

        with patch(
            "app.obsidian.infrastructure.obsidian_report_bundle_run_store.os.replace",
            gated_replace,
        ):
            try:
                first_task = asyncio.create_task(service.upsert(first_request))
                tasks.append(first_task)
                await asyncio.wait_for(entered.wait(), timeout=3)

                first_task.cancel()
                await _next_loop_turn()
                assert not first_task.done(), (
                    "cancelled upsert returned before its typed intent save completed"
                )
                assert coordinator.active_operation == "obsidian_verified_upsert"

                first_task.cancel()
                await _next_loop_turn()
                assert not first_task.done(), (
                    "repeated cancellation released the upsert before intent durability"
                )
                assert coordinator.active_operation == "obsidian_verified_upsert"

                retry_task = asyncio.create_task(service.upsert(retry_request))
                tasks.append(retry_task)
                await _next_loop_turn()
                assert not retry_task.done()
                assert ports.resolutions == 1, (
                    "same-key retry reached the public write flow while the first "
                    "intent replacement was still blocked"
                )

                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(first_task, timeout=3)
                with pytest.raises(ObsidianIdempotencyConflictError):
                    await asyncio.wait_for(retry_task, timeout=3)

                stored = checkpoint_store.load_typed(checkpoint_key, checkpoint_adapter)
                assert stored is not None
                assert stored.state is ObsidianVerifiedCheckpointState.INTENT_RECORDED
                assert stored.request_hash == verified_upsert_request_hash(
                    first_request
                )
                assert ports.writes == 0
            finally:
                await _drain_gate_and_tasks(
                    entered=entered,
                    release=release,
                    replaced=replaced,
                    tasks=tasks,
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ("relate", "receipt"))
def test_typed_checkpoint_leaf_retains_writer_lease_until_save_completes(
    tmp_path: Path,
    kind: str,
) -> None:
    """Leaf-save contract only: durable typed records cannot be overwritten late."""

    async def scenario() -> None:
        coordinator = IndexMaintenanceCoordinator()
        store = ObsidianReportBundleRunStore(tmp_path)
        if kind == "relate":
            checkpoint_key = "relate:cancelled-leaf"
            relation = ObsidianRelationType.DERIVED_FROM
            result = ObsidianRelateResult(
                completion_status=(
                    ObsidianRelateCompletionStatus.STORED_WITH_PROJECTION_WARNINGS
                ),
                idempotency_key="cancelled-leaf",
                replayed=False,
                source_note_id="source",
                target_note_id="target",
                relation=relation,
                source_path="source.md",
                target_path="target.md",
                operation=ObsidianWriteOperation.UPDATED,
                content_hash="a" * 64,
                storage_status="stored",
                metadata_status="unknown",
                fts_status="unknown",
                graph_edge_index_status="unknown",
                graph_projection_status="unknown",
                source_link_verified=True,
                target_backlink_verified=False,
                related_notes_verified=False,
            )
            original = ObsidianRelateCheckpoint(
                request_hash="a" * 64,
                source_note_id="source",
                target_note_id="target",
                relation=relation,
                source_content_hash="a" * 64,
                result=result,
            )
            newer: CheckpointRecord = replace(
                original,
                result=replace(
                    result,
                    completion_status=ObsidianRelateCompletionStatus.COMPLETED,
                    graph_projection_status="current",
                    target_backlink_verified=True,
                    related_notes_verified=True,
                ),
            )
            adapter = TypeAdapter(ObsidianRelateCheckpoint)
        else:
            idempotency_key = "cancelled-leaf-receipt"
            checkpoint_key = ReceiptIdentityPolicy.mutation_id(idempotency_key)
            receipts = NoteMutationReceipts(
                ObsidianVaultConfigStore(
                    default_vault_path=str(tmp_path),
                    default_alexandria_root="Alexandria",
                    config_path=None,
                )
            )
            original = NoteMutationReceipt(
                idempotency_key=idempotency_key,
                mutation_id=checkpoint_key,
                operation_identity="a" * 64,
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
            )
            newer = replace(
                original,
                status=ObsidianMutationOutcomeStatus.COMMITTED,
                effect_started=True,
                canonical_path="Alexandria/test.md",
                note_id="test",
                expected_source_hash="b" * 64,
                content_hash="b" * 64,
                committed_at=datetime(2026, 11, 7, tzinfo=UTC),
            )
            adapter = TypeAdapter(NoteMutationReceipt)

        newer_entered = asyncio.Event()
        entered, release, replaced, gated_replace = _replace_gate(
            asyncio.get_running_loop()
        )
        tasks: list[asyncio.Task[object]] = []

        async def save(record: CheckpointRecord) -> None:
            if isinstance(record, ObsidianRelateCheckpoint):
                await save_checkpoint(store, checkpoint_key, record)
            else:
                await receipts.save(record)

        async def write(record: CheckpointRecord, *, is_newer: bool = False) -> None:
            async with coordinator.operation(f"obsidian_{kind}", wait=True):
                if is_newer:
                    newer_entered.set()
                await save(record)

        with patch(
            "app.obsidian.infrastructure.obsidian_report_bundle_run_store.os.replace",
            gated_replace,
        ):
            try:
                first_task = asyncio.create_task(write(original))
                tasks.append(first_task)
                await asyncio.wait_for(entered.wait(), timeout=3)

                first_task.cancel()
                await _next_loop_turn()
                assert not first_task.done(), (
                    f"{kind} checkpoint save returned before typed replacement completed"
                )
                assert coordinator.active_operation == f"obsidian_{kind}"

                first_task.cancel()
                await _next_loop_turn()
                assert not first_task.done(), (
                    f"repeated cancellation released {kind} writer ownership early"
                )
                assert coordinator.active_operation == f"obsidian_{kind}"

                newer_task = asyncio.create_task(write(newer, is_newer=True))
                tasks.append(newer_task)
                await _next_loop_turn()
                assert not newer_entered.is_set()
                assert not newer_task.done()
                assert store.load_typed(checkpoint_key, adapter) is None

                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(first_task, timeout=3)
                await asyncio.wait_for(newer_task, timeout=3)

                stored = store.load_typed(checkpoint_key, adapter)
                assert stored == newer
            finally:
                await _drain_gate_and_tasks(
                    entered=entered,
                    release=release,
                    replaced=replaced,
                    tasks=tasks,
                )

    asyncio.run(scenario())
