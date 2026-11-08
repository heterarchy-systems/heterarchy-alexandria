"""Canonical Obsidian note mutation and index write-through service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial

from app.obsidian.application.notes.mutations.receipt_identity import (
    ReceiptIdentityPolicy,
)
from app.obsidian.application.notes.mutations.receipts import (
    NoteMutationReceipts,
)
from app.obsidian.application.notes.reading.obsidian_note_readback import (
    ObsidianNoteReadback,
)
from app.obsidian.application.notes.reading.obsidian_note_reader import (
    ObsidianNoteReader,
)
from app.obsidian.application.notes.writing import (
    ObsidianNoteBodyPatcher,
    ObsidianNoteRepair,
    ObsidianNoteRevalidation,
)
from app.obsidian.application.notes.writing.obsidian_note_persistence import (
    record_index_error_best_effort,
)
from app.obsidian.application.notes.writing.obsidian_note_writer import (
    ObsidianNoteWriter,
)
from app.obsidian.application.service.notes.obsidian_note_service_contracts import (
    ObsidianNoteSupersedeHook,
)
from app.obsidian.application.service.notes.obsidian_write_target_resolver import (
    ObsidianWriteTargetResolver,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianSearchQuery,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import NoteMutationReceipt
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteWriteResult,
    ObsidianReindexResult,
    ObsidianSearchHit,
    ObsidianVaultSourceSnapshot,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexStatus,
    ObsidianWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.operations.application.skill_contract.skill_publication_policy import (
    SkillPublicationPolicy,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
    ObsidianIdentityConflictError,
    ObsidianNotFoundError,
    ObsidianWriteConflictError,
)


@dataclass(frozen=True, slots=True)
class NoteMutationAdmission:
    """Immutable receipt and replay outcome for one admitted mutation."""

    receipt: NoteMutationReceipt
    replay: ObsidianNote | None


class ObsidianNoteService:
    """Own note mutations, Markdown persistence, and index write-through."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
        mark_context_superseded: ObsidianNoteSupersedeHook,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        source_snapshot: Callable[[int], Awaitable[ObsidianVaultSourceSnapshot]],
        source_scan_limit: int,
        skill_publication_policy: SkillPublicationPolicy | None = None,
    ) -> None:
        """Create the canonical note service.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_config_store: Runtime vault location provider.
            reindex: Vault index refresh callback.
            mark_context_superseded: Context lifecycle reconciliation callback.
            index_maintenance_coordinator: Process-wide rebuildable-index write lane.
            source_snapshot: Source-owned bounded Markdown snapshot callback.
            source_scan_limit: Maximum source files to scan for ID fallback reads.
            skill_publication_policy: Active Skill admission, composed lazily if absent.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._reindex = reindex
        self._mark_context_superseded = mark_context_superseded
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._reader = ObsidianNoteReader(
            repository=repository,
            vault_config_store=vault_config_store,
            source_snapshot=source_snapshot,
            source_scan_limit=source_scan_limit,
        )
        self._readback = ObsidianNoteReadback(
            repository=repository, vault_config_store=vault_config_store
        )
        self._mutation_receipts = NoteMutationReceipts(vault_config_store)
        self._skill_publication_policy = skill_publication_policy
        self._record_index_error = partial(
            record_index_error_best_effort,
            repository=repository,
        )
        self._write_target_resolver = ObsidianWriteTargetResolver(
            repository=repository,
            vault_config_store=vault_config_store,
            reindex=reindex,
        )
        self._writer = ObsidianNoteWriter(
            repository=repository,
            vault_config_store=vault_config_store,
            write_target_resolver=self._write_target_resolver,
            mutation_receipts=self._mutation_receipts,
            mark_context_superseded=self._mark_context_superseded,
            skill_publication_policy=skill_publication_policy,
            record_index_error=self._record_index_error,
        )
        self._repairer = ObsidianNoteRepair(
            repository=repository,
            vault_config_store=vault_config_store,
            index_maintenance_coordinator=index_maintenance_coordinator,
            record_index_error=self._record_index_error,
            skill_publication_policy=skill_publication_policy,
        )
        self._body_patcher = ObsidianNoteBodyPatcher(
            repository=repository,
            vault_config_store=vault_config_store,
            index_maintenance_coordinator=index_maintenance_coordinator,
            record_index_error=self._record_index_error,
        )
        self._revalidation = ObsidianNoteRevalidation(
            repository=repository,
            vault_config_store=vault_config_store,
            index_maintenance_coordinator=index_maintenance_coordinator,
            record_index_error=self._record_index_error,
        )

    @property
    def reader(self) -> ObsidianNoteReader:
        """Return the composition-owned Markdown source reader.

        Returns:
            Reader sharing this service's repository and Vault configuration.
        """
        return self._reader

    @property
    def readback(self) -> ObsidianNoteReadback:
        """Return the composition-owned indexed-readback verifier.

        Returns:
            Readback verifier sharing the repository and Vault configuration.
        """
        return self._readback

    @property
    def repairer(self) -> ObsidianNoteRepair:
        """Return the composition-owned raw and frontmatter repair service.

        Returns:
            Repair service sharing this service's write lane.
        """
        return self._repairer

    @property
    def body_patcher(self) -> ObsidianNoteBodyPatcher:
        """Return the composition-owned bounded body patcher.

        Returns:
            Body patch service sharing this service's write lane.
        """
        return self._body_patcher

    @property
    def revalidation(self) -> ObsidianNoteRevalidation:
        """Return the composition-owned single-note index revalidator.

        Returns:
            Revalidation service sharing this service's write lane.
        """
        return self._revalidation

    @property
    def write_target_resolver(self) -> ObsidianWriteTargetResolver:
        """Return the shared path and identity resolver.

        Returns:
            Resolver shared by write orchestration and the facade's lifecycle callback.
        """
        return self._write_target_resolver

    async def search(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = False,
    ) -> list[ObsidianSearchHit]:
        """Search Obsidian notes through the PostgreSQL index.

        Args:
            query: Search filters and query text.
            refresh: Whether to re-scan the vault before querying.

        Returns:
            Ranked search hits.
        """
        if refresh:
            await self._reindex()
        return await self._repository.search(query)

    async def save_note(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Create or replace one Alexandria-managed Markdown note.

        Args:
            payload: Save request with body and metadata.

        Returns:
            Saved note loaded through the index.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_note_mutation", wait=True
        ):
            admission = await self._admit_note_mutation(payload)
            receipt = admission.receipt
            if admission.replay is not None:
                return admission.replay
            try:
                commit = await self._writer.save_note_serialized(
                    payload=payload,
                    receipt=receipt,
                )
                note = commit.note
                note.mutation_receipt = await self._mutation_receipts.completed(
                    receipt=receipt, note=note
                )
                return note
            except Exception as exc:
                await self._mutation_receipts.failed(
                    receipt=receipt,
                    error=exc,
                    conflicted=isinstance(
                        exc, (ObsidianWriteConflictError, ObsidianIdentityConflictError)
                    ),
                )
                raise

    async def write_note(
        self,
        command: ObsidianWriteNote,
    ) -> ObsidianNoteWriteResult:
        """Execute an explicit create, update, or upsert without identity guessing.

        Args:
            command: Value supplied to write_note.

        Returns:
            Result produced by write_note.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_explicit_note_write",
            wait=True,
        ):
            admission = await self._admit_note_mutation(
                payload=command.note, command=command
            )
            receipt = admission.receipt
            if admission.replay is not None:
                note, mutated, source_hash = (
                    admission.replay,
                    False,
                    admission.replay.source_hash,
                )
                expected_operation = ObsidianWriteOperation.UNCHANGED
            else:
                try:
                    (
                        payload,
                        existing,
                        expected_operation,
                    ) = await self._write_target_resolver.resolve(command)
                    commit = await self._writer.save_note_serialized(
                        payload=payload,
                        existing_note=existing,
                        frontmatter_mode=command.frontmatter_mode,
                        receipt=receipt,
                    )
                    note, mutated, source_hash = (
                        commit.note,
                        commit.mutated,
                        commit.source_hash,
                    )
                    note.mutation_receipt = await self._mutation_receipts.completed(
                        receipt=receipt, note=note
                    )
                except Exception as exc:
                    await self._mutation_receipts.failed(
                        receipt=receipt,
                        error=exc,
                        conflicted=isinstance(
                            exc,
                            (ObsidianWriteConflictError, ObsidianIdentityConflictError),
                        ),
                    )
                    raise
        operation = expected_operation if mutated else ObsidianWriteOperation.UNCHANGED
        return ObsidianNoteWriteResult(
            operation=operation,
            write_mode=command.write_mode,
            match_by=command.match_by,
            note=note,
            storage_status="stored" if mutated else "unchanged",
            metadata_status=note.index_status.value,
            fts_status="indexed"
            if note.index_status is ObsidianIndexStatus.INDEXED
            else "unknown",
            graph_edge_index_status="indexed"
            if note.index_status is ObsidianIndexStatus.INDEXED
            else "unknown",
            graph_projection_status="stale" if mutated else "unknown",
            reindex_required=mutated
            or (
                note.mutation_receipt is not None
                and note.mutation_receipt.error_summary is not None
            ),
            warnings=("mutation_pipeline_reconciliation_required",)
            if note.mutation_receipt is not None
            and note.mutation_receipt.error_summary is not None
            else (),
            source_hash=source_hash,
        )

    async def _admit_note_mutation(
        self,
        payload: ObsidianSaveNote,
        command: ObsidianWriteNote | None = None,
    ) -> NoteMutationAdmission:
        """Read back existing effects before target selection or source mutation.

        Args:
            payload: Validated save payload used to identify the mutation.
            command: Explicit write command when this is a mode-specific write.

        Returns:
            The admitted receipt and a verified replay note when available.
        """
        key, identity = ReceiptIdentityPolicy.request_identity(
            payload=payload, command=command
        )
        receipt = await self._mutation_receipts.admit(key=key, identity=identity)
        if not receipt.effect_started:
            return NoteMutationAdmission(receipt=receipt, replay=None)
        try:
            note = await self._reader.read_note_by_path(receipt.canonical_path or "")
        except ObsidianNotFoundError:
            note = None
        outcome = await self._mutation_receipts.observe(receipt=receipt, note=note)
        if (
            outcome.status is ObsidianMutationOutcomeStatus.COMMITTED
            and note is not None
        ):
            note.mutation_receipt = replace(outcome, replayed=True)
            return NoteMutationAdmission(receipt=receipt, replay=note)
        if outcome.status is ObsidianMutationOutcomeStatus.NOT_COMMITTED:
            admitted = replace(
                receipt,
                effect_started=False,
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
            )
            await self._mutation_receipts.save(admitted)
            return NoteMutationAdmission(receipt=admitted, replay=None)
        if outcome.status is ObsidianMutationOutcomeStatus.CONFLICTED:
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: mutation source drifted; reconcile before retry"
            )
        raise ObsidianCheckpointRecoveryRequiredError(receipt.mutation_id)
