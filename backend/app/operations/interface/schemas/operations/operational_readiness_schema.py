"""HTTP schemas for operational readiness."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.memory.interface.schemas.context.context_index_schema import (
    ContextEmbeddingSourceStatusResponse,
)
from app.memory.interface.schemas.context.context_mapping import source_status_payload
from app.operations.domain.entities.operational_readiness import (
    OperationalCompileReceiptSnapshot,
    OperationalDatabaseSnapshot,
    OperationalGraphSnapshot,
    OperationalRagSnapshot,
    OperationalReconciliationSnapshot,
    OperationalVaultSnapshot,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject


class OperationalVaultSnapshotResponse(StrictSchemaModel):
    """Vault state in the operational readiness response."""

    exists: Annotated[
        bool, Field(description="Exists for this operational vault snapshot response.")
    ]
    readable: Annotated[
        bool,
        Field(description="Readable for this operational vault snapshot response."),
    ]
    vault_path: Annotated[
        str,
        Field(description="Vault path for this operational vault snapshot response."),
    ]
    alexandria_root: Annotated[
        str,
        Field(
            description="Alexandria root for this operational vault snapshot response."
        ),
    ]
    alexandria_root_exists: Annotated[
        bool,
        Field(
            description="Alexandria root exists for this operational vault snapshot response."
        ),
    ]
    indexed_notes: Annotated[
        int | None,
        Field(
            description="Indexed notes for this operational vault snapshot response."
        ),
    ]
    stale_notes: Annotated[
        int | None,
        Field(description="Stale notes for this operational vault snapshot response."),
    ]
    error_notes: Annotated[
        int | None,
        Field(description="Error notes for this operational vault snapshot response."),
    ]

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalVaultSnapshot,
    ) -> OperationalVaultSnapshotResponse:
        """Create response schema from read model.

        Args:
            snapshot: Vault readiness read model.

        Returns:
            Vault response schema.
        """
        return cls(
            exists=snapshot.exists,
            readable=snapshot.readable,
            vault_path=snapshot.vault_path,
            alexandria_root=snapshot.alexandria_root,
            alexandria_root_exists=snapshot.alexandria_root_exists,
            indexed_notes=snapshot.indexed_notes,
            stale_notes=snapshot.stale_notes,
            error_notes=snapshot.error_notes,
        )


class OperationalDatabaseSnapshotResponse(StrictSchemaModel):
    """Database state in the operational readiness response."""

    reachable: Annotated[
        bool,
        Field(description="Reachable for this operational database snapshot response."),
    ]
    integrity: Annotated[
        str,
        Field(description="Integrity for this operational database snapshot response."),
    ]
    schema_version: Annotated[
        str | None,
        Field(
            description="Schema version for this operational database snapshot response."
        ),
    ]
    corruption_detected: Annotated[
        bool,
        Field(
            description="Corruption detected for this operational database snapshot response."
        ),
    ] = False

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalDatabaseSnapshot,
    ) -> OperationalDatabaseSnapshotResponse:
        """Create response schema from read model.

        Args:
            snapshot: Database readiness read model.

        Returns:
            Database response schema.
        """
        return cls(
            reachable=snapshot.reachable,
            integrity=snapshot.integrity,
            schema_version=snapshot.schema_version,
            corruption_detected=snapshot.corruption_detected,
        )


class OperationalGraphSnapshotResponse(StrictSchemaModel):
    """Graph projection status evidence."""

    status: Annotated[str, Field(description="Graph projection status.")]
    enabled: Annotated[bool, Field(description="Whether graph projection is enabled.")]
    node_count: Annotated[int | None, Field(description="Observed graph node count.")]
    edge_count: Annotated[int | None, Field(description="Observed graph edge count.")]
    run_id: Annotated[
        str | None, Field(description="Graph projection activation run id.")
    ]
    projection_revision: Annotated[
        str | None,
        Field(description="Graph projection activation revision."),
    ]
    warnings: Annotated[list[str], Field(description="Graph status warnings.")] = (
        schema_list_default()
    )
    recommended_operation: Annotated[
        str | None,
        Field(description="Detail API that lists the exact graph issues."),
    ] = None

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalGraphSnapshot,
    ) -> OperationalGraphSnapshotResponse:
        """Map graph status evidence to the HTTP contract."""
        return cls(
            status=snapshot.status,
            enabled=snapshot.enabled,
            node_count=snapshot.node_count,
            edge_count=snapshot.edge_count,
            run_id=snapshot.run_id,
            projection_revision=snapshot.projection_revision,
            warnings=list(snapshot.warnings),
            recommended_operation=snapshot.recommended_operation,
        )


class OperationalCompileReceiptSnapshotResponse(StrictSchemaModel):
    """Latest knowledge compile receipt evidence."""

    available: Annotated[bool, Field(description="Whether a receipt is persisted.")]
    required: Annotated[
        bool, Field(description="Whether this path requires compiler evidence.")
    ]
    status: Annotated[
        str, Field(description="Receipt necessity, validity and revision state.")
    ]
    blockers: Annotated[list[str], Field(description="Blocking receipt failures.")]
    applied_at: Annotated[
        datetime | None,
        Field(description="Timestamp of the last successful compile application."),
    ] = None
    plan_fingerprint: Annotated[
        str | None,
        Field(description="Fingerprint of the applied compile plan."),
    ] = None
    policy_version: Annotated[
        str | None, Field(description="Compile policy version fingerprint.")
    ] = None
    changed_documents: Annotated[
        int | None, Field(description="Documents changed by the applied plan.")
    ] = None
    removed_documents: Annotated[
        int | None, Field(description="Documents removed by the applied plan.")
    ] = None
    embedding_invalidated_documents: Annotated[
        int | None,
        Field(description="Documents whose chunks must re-embed."),
    ] = None
    diagnostic_count: Annotated[
        int | None, Field(description="Diagnostics emitted by the compile.")
    ] = None
    warnings: Annotated[list[str], Field(description="Receipt warnings.")] = (
        schema_list_default()
    )

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalCompileReceiptSnapshot,
    ) -> OperationalCompileReceiptSnapshotResponse:
        """Map the readiness entity to the HTTP contract."""
        return cls(
            available=snapshot.available,
            required=snapshot.required,
            status=snapshot.status.value,
            blockers=list(snapshot.blockers),
            applied_at=snapshot.applied_at,
            plan_fingerprint=snapshot.plan_fingerprint,
            policy_version=snapshot.policy_version,
            changed_documents=snapshot.changed_documents,
            removed_documents=snapshot.removed_documents,
            embedding_invalidated_documents=(snapshot.embedding_invalidated_documents),
            diagnostic_count=snapshot.diagnostic_count,
            warnings=list(snapshot.warnings),
        )


class OperationalRagSnapshotResponse(StrictSchemaModel):
    """RAG state in the operational readiness response."""

    fts: Annotated[
        str, Field(description="FTS for this operational RAG snapshot response.")
    ]
    vector: Annotated[
        str, Field(description="Vector for this operational RAG snapshot response.")
    ]
    embedding: Annotated[
        str, Field(description="Embedding for this operational RAG snapshot response.")
    ]
    effective_strategy: Annotated[
        str,
        Field(
            description="Effective strategy for this operational RAG snapshot response."
        ),
    ]
    model_name: Annotated[
        str, Field(description="Model name for this operational RAG snapshot response.")
    ]
    dimensions: Annotated[
        int, Field(description="Dimensions for this operational RAG snapshot response.")
    ]
    fingerprint: Annotated[
        JSONObject | None,
        Field(description="Fingerprint for this operational RAG snapshot response."),
    ]
    source_statuses: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        Field(
            description="Source statuses for this operational RAG snapshot response."
        ),
    ] = schema_list_default()
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this operational RAG snapshot response."),
    ] = schema_list_default()

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalRagSnapshot,
    ) -> OperationalRagSnapshotResponse:
        """Create response schema from read model.

        Args:
            snapshot: RAG readiness read model.

        Returns:
            RAG response schema.
        """
        return cls(
            fts=snapshot.fts.value,
            vector=snapshot.vector.value,
            embedding=snapshot.embedding.value,
            effective_strategy=snapshot.effective_strategy.value,
            model_name=snapshot.model_name,
            dimensions=snapshot.dimensions,
            fingerprint=snapshot.fingerprint,
            source_statuses=[
                ContextEmbeddingSourceStatusResponse.model_validate(
                    source_status_payload(status)
                )
                for status in snapshot.source_statuses
            ],
            warnings=list(snapshot.warnings),
        )


class OperationalReconciliationSnapshotResponse(StrictSchemaModel):
    """Memory reconciliation state in the operational readiness response."""

    configured: Annotated[
        bool,
        Field(
            description="Configured for this operational reconciliation snapshot response."
        ),
    ]
    reachable: Annotated[
        bool,
        Field(
            description="Reachable for this operational reconciliation snapshot response."
        ),
    ]
    total_contexts: Annotated[
        int,
        Field(
            description="Total contexts for this operational reconciliation snapshot response."
        ),
    ]
    temporal_state_count: Annotated[
        int,
        Field(
            description="Temporal state count for this operational reconciliation snapshot response."
        ),
    ]
    missing_temporal_states: Annotated[
        int,
        Field(
            description="Missing temporal states for this operational reconciliation snapshot response."
        ),
    ]
    backfill_complete: Annotated[
        bool,
        Field(
            description="Backfill complete for this operational reconciliation snapshot response."
        ),
    ]
    total_plans: Annotated[
        int,
        Field(
            description="Total plans for this operational reconciliation snapshot response."
        ),
    ]
    pending_review_plans: Annotated[
        int,
        Field(
            description="Pending review plans for this operational reconciliation snapshot response."
        ),
    ]
    total_results: Annotated[
        int,
        Field(
            description="Total results for this operational reconciliation snapshot response."
        ),
    ]
    partial_apply_results: Annotated[
        int,
        Field(
            description="Partial apply results for this operational reconciliation snapshot response."
        ),
    ]
    failed_results: Annotated[
        int,
        Field(
            description="Failed results for this operational reconciliation snapshot response."
        ),
    ]
    open_conflicts: Annotated[
        int,
        Field(
            description="Open conflicts for this operational reconciliation snapshot response."
        ),
    ]
    reviewing_conflicts: Annotated[
        int,
        Field(
            description="Reviewing conflicts for this operational reconciliation snapshot response."
        ),
    ]
    hard_delete_results: Annotated[
        int,
        Field(
            description="Hard delete results for this operational reconciliation snapshot response."
        ),
    ]
    latest_failure_code: Annotated[
        str | None,
        Field(
            description="Latest failure code for this operational reconciliation snapshot response."
        ),
    ]
    latest_failure_at: Annotated[
        AwareTimestamp | None,
        Field(
            description="Latest failure at for this operational reconciliation snapshot response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalReconciliationSnapshot,
    ) -> OperationalReconciliationSnapshotResponse:
        """Create response schema from reconciliation readiness state.

        Args:
            snapshot: Snapshot.

        Returns:
            OperationalReconciliationSnapshotResponse: Operation result.
        """
        return cls(
            configured=snapshot.configured,
            reachable=snapshot.reachable,
            total_contexts=snapshot.total_contexts,
            temporal_state_count=snapshot.temporal_state_count,
            missing_temporal_states=snapshot.missing_temporal_states,
            backfill_complete=snapshot.backfill_complete,
            total_plans=snapshot.total_plans,
            pending_review_plans=snapshot.pending_review_plans,
            total_results=snapshot.total_results,
            partial_apply_results=snapshot.partial_apply_results,
            failed_results=snapshot.failed_results,
            open_conflicts=snapshot.open_conflicts,
            reviewing_conflicts=snapshot.reviewing_conflicts,
            hard_delete_results=snapshot.hard_delete_results,
            latest_failure_code=snapshot.latest_failure_code,
            latest_failure_at=snapshot.latest_failure_at,
        )
