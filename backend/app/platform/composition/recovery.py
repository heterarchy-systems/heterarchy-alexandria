"""Compose operational recovery callbacks over their existing effect owners."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.memory.application.contexts.embedding.context_embedding_recovery_service import (
    ContextEmbeddingRecoveryService,
)
from app.memory.application.contexts.records.context_service_ports import (
    ContextRecoveryPort,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.domain.entities.context_read_models import ContextReindexResult
from app.obsidian.application.graph.diagnostics.obsidian_graph_issue_list_service import (
    ObsidianGraphIssueListService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.notes.mutations.outcome_service import (
    ObsidianMutationOutcomeService,
)
from app.obsidian.domain.contracts.obsidian_graph_issue_contracts import (
    ObsidianGraphIssueListQuery,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    ObsidianMutationOutcome,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.operations.application.maintenance_dlq_service import (
    MaintenanceDeadLetterLifecycleService,
)
from app.operations.application.maintenance_job_queue import MaintenanceJobSubmitter
from app.operations.application.recovery.execution.recovery_run_contracts import (
    RecoveryCallbacks,
    resolve_recovery_service,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
)
from app.operations.infrastructure.maintenance_job_payload_store import (
    MaintenanceJobPayloadStore,
)
from app.platform.composition.recovery_payloads import (
    RecoveryCurrentCompactPayload,
    RecoveryDeadLetterEntryPayload,
    RecoveryDeadLetterOutcomePayload,
    RecoveryDeadLetterPayload,
    RecoveryEmbeddingBatchPayload,
    RecoveryEmbeddingPayload,
    RecoveryPayloadMapper,
)
from app.platform.config.memory_config import EmbeddingConfig
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONObject, JSONValue


def create_maintenance_dlq_service(
    database: Database,
    queue: MaintenanceJobSubmitter | None,
    archive_namespace: str,
    outcome_factory: Callable[
        [], ObsidianMutationOutcomeService | Awaitable[ObsidianMutationOutcomeService]
    ],
) -> MaintenanceDeadLetterLifecycleService | None:
    """Compose DLQ coordination with its existing durable/effect owners.

    Args:
        database: Existing PostgreSQL transaction owner.
        queue: Existing Redis queue, absent when disabled.
        archive_namespace: Configured DLQ stream identity.
        outcome_factory: Request-scoped canonical note receipt reader.

    Returns:
        Enabled lifecycle service or explicit disabled capability.
    """
    if queue is None:
        return None

    async def read_payload(identity: str) -> dict[str, JSONValue] | None:
        async with database.request_session() as session:
            return await MaintenanceJobPayloadStore(session).load(identity)

    async def write_archive(identity: str, body: dict[str, JSONValue]) -> bool:
        async with database.request_session() as session:
            return await MaintenanceJobPayloadStore(session).save_if_absent(
                identity, "maintenance_dlq_retirement", body
            )

    async def read_outcome(identity: str) -> ObsidianMutationOutcome:
        async with database.request_session():
            service = await resolve_recovery_service(outcome_factory)
            return await service.note_write_outcome(identity)

    return MaintenanceDeadLetterLifecycleService(
        queue,
        archive_namespace=archive_namespace,
        payload_reader=read_payload,
        archive_reader=read_payload,
        archive_writer=write_archive,
        note_outcome_reader=read_outcome,
    )


def create_recovery_callbacks(
    config: EmbeddingConfig,
    database: Database,
    embedding_owner: ContextEmbeddingRecoveryService,
    graph_factory: Callable[
        [],
        ObsidianGraphProjectionRebuildService
        | Awaitable[ObsidianGraphProjectionRebuildService],
    ],
    links_factory: Callable[
        [], ObsidianGraphIssueListService | Awaitable[ObsidianGraphIssueListService]
    ],
    compact_factory: Callable[
        [], MemoryCompactService | Awaitable[MemoryCompactService]
    ],
    queue: MaintenanceJobSubmitter | None,
    dlq_service: MaintenanceDeadLetterLifecycleService | None,
) -> RecoveryCallbacks:
    """Bind recovery to existing owners with independent transactions and bounded reads.

    Args:
        config: Loaded batch ceilings.
        database: Canonical request transaction owner.
        embedding_owner: Existing resumable embedding invalidation owner.
        graph_factory: Session-bound graph rebuild provider.
        links_factory: Session-bound Rust graph diagnostics provider.
        compact_factory: Existing CURRENT source reader provider.
        queue: Optional existing Redis maintenance queue.
        dlq_service: Optional receipt-based DLQ reconciler.

    Returns:
        Capability bindings; construction performs no recovery effects.
    """

    async def embeddings(
        context: ContextRecoveryPort, batch_size: int, max_batches: int
    ) -> JSONObject:
        if (batch_size, max_batches) != (
            config.rag_embedding_recovery_batch_size,
            config.rag_embedding_recovery_max_batches,
        ):
            raise ValueError("embedding recovery bounds differ from configured owner")
        batches: list[ContextReindexResult] = []
        result = await embedding_owner.recover(context, batch_observer=batches.append)
        batch_payloads = [
            dict[str, JSONValue](
                **RecoveryEmbeddingBatchPayload(
                    scanned=batch.scanned,
                    updated=batch.updated,
                    skipped=batch.skipped,
                    warnings=list(batch.warnings),
                )
            )
            for batch in batches
        ]
        payload = RecoveryEmbeddingPayload(
            scanned=result.scanned,
            updated=result.updated,
            skipped=result.skipped,
            warnings=list(result.warnings),
            batches=batch_payloads,
            batch_size=batch_size,
            max_batches=max_batches,
        )
        return dict[str, JSONValue](**payload)

    async def graph() -> JSONObject:
        async with database.request_session():
            service = await resolve_recovery_service(graph_factory)
            result = await service.rebuild()
            return RecoveryPayloadMapper.graph_rebuild(result)

    async def links() -> JSONObject:
        async with database.request_session():
            service = await resolve_recovery_service(links_factory)
            result = await service.list_issues(ObsidianGraphIssueListQuery(limit=50))
            return RecoveryPayloadMapper.graph_issue_list(result)

    async def dlq() -> JSONObject:
        if queue is None or dlq_service is None:
            payload = RecoveryDeadLetterPayload(
                enabled=False,
                ready=True,
                entries=[],
                truncated=False,
            )
            return dict[str, JSONValue](**payload)
        entries = await queue.list_dead_letters(51)
        results: list[RecoveryDeadLetterEntryPayload] = []
        ready = len(entries) <= 50
        for entry in entries[:50]:
            outcome = await dlq_service.reconcile(entry.entry_id)
            unresolved = (
                not outcome.source_available
                or outcome.outcome_class.value
                in {
                    MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME.value,
                    MaintenanceDeadLetterOutcomeClass.CONFLICT.value,
                }
                or any(
                    item.status
                    in {
                        ObsidianMutationOutcomeStatus.UNKNOWN.value,
                        ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED.value,
                        ObsidianMutationOutcomeStatus.CONFLICTED.value,
                    }
                    for item in outcome.items
                )
            )
            ready = ready and not unresolved
            outcomes = [
                RecoveryDeadLetterOutcomePayload(
                    status=item.status,
                    effect_identity=item.effect_identity,
                )
                for item in outcome.items
            ]
            json_outcomes = [
                dict[str, JSONValue](**item_outcome) for item_outcome in outcomes
            ]
            results.append(
                RecoveryDeadLetterEntryPayload(
                    entry_id=entry.entry_id,
                    ready=not unresolved,
                    outcomes=json_outcomes,
                )
            )
        payload = RecoveryDeadLetterPayload(
            enabled=True,
            ready=ready,
            entries=[dict[str, JSONValue](**entry) for entry in results],
            truncated=len(entries) > 50,
        )
        return dict[str, JSONValue](**payload)

    async def current() -> JSONObject:
        async with database.request_session():
            service = await resolve_recovery_service(compact_factory)
            compact = await service.current()
            payload = RecoveryCurrentCompactPayload(
                project=None,
                available=compact is not None,
                compact_id=None if compact is None else compact.id,
                status="NOT_APPLICABLE" if compact is None else compact.status.value,
                scope="default_project",
            )
            return dict[str, JSONValue](**payload)

    return RecoveryCallbacks(
        embedding=embeddings,
        graph=graph,
        links=links,
        dlq=dlq,
        current=current,
        embedding_batch_size=config.rag_embedding_recovery_batch_size,
        embedding_max_batches=config.rag_embedding_recovery_max_batches,
    )
