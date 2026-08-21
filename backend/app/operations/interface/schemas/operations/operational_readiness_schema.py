"""HTTP schemas for operational readiness."""

from __future__ import annotations

from typing import Annotated

from app.memory.interface.schemas.context.context_mapping import source_status_payload
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextEmbeddingSourceStatusResponse,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalDatabaseSnapshot,
    OperationalRagSnapshot,
    OperationalReconciliationSnapshot,
    OperationalVaultSnapshot,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject


class OperationalVaultSnapshotResponse(StrictSchemaModel):
    """Vault state in the operational readiness response."""

    exists: Annotated[
        bool, described_field("Exists for this operational vault snapshot response.")
    ]
    readable: Annotated[
        bool, described_field("Readable for this operational vault snapshot response.")
    ]
    vault_path: Annotated[
        str, described_field("Vault path for this operational vault snapshot response.")
    ]
    alexandria_root: Annotated[
        str,
        described_field(
            "Alexandria root for this operational vault snapshot response."
        ),
    ]
    alexandria_root_exists: Annotated[
        bool,
        described_field(
            "Alexandria root exists for this operational vault snapshot response."
        ),
    ]
    indexed_notes: Annotated[
        int,
        described_field("Indexed notes for this operational vault snapshot response."),
    ]
    stale_notes: Annotated[
        int,
        described_field("Stale notes for this operational vault snapshot response."),
    ]
    error_notes: Annotated[
        int,
        described_field("Error notes for this operational vault snapshot response."),
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
        described_field("Reachable for this operational database snapshot response."),
    ]
    integrity: Annotated[
        str,
        described_field("Integrity for this operational database snapshot response."),
    ]
    schema_version: Annotated[
        str | None,
        described_field(
            "Schema version for this operational database snapshot response."
        ),
    ]
    corruption_detected: Annotated[
        bool,
        described_field(
            "Corruption detected for this operational database snapshot response."
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


class OperationalRagSnapshotResponse(StrictSchemaModel):
    """RAG state in the operational readiness response."""

    fts: Annotated[
        str, described_field("FTS for this operational RAG snapshot response.")
    ]
    vector: Annotated[
        str, described_field("Vector for this operational RAG snapshot response.")
    ]
    embedding: Annotated[
        str, described_field("Embedding for this operational RAG snapshot response.")
    ]
    effective_strategy: Annotated[
        str,
        described_field(
            "Effective strategy for this operational RAG snapshot response."
        ),
    ]
    model_name: Annotated[
        str, described_field("Model name for this operational RAG snapshot response.")
    ]
    dimensions: Annotated[
        int, described_field("Dimensions for this operational RAG snapshot response.")
    ]
    fingerprint: Annotated[
        JSONObject | None,
        described_field("Fingerprint for this operational RAG snapshot response."),
    ]
    source_statuses: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        described_field("Source statuses for this operational RAG snapshot response."),
    ] = schema_list_default()
    warnings: Annotated[
        list[str],
        described_field("Warnings for this operational RAG snapshot response."),
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
        described_field(
            "Configured for this operational reconciliation snapshot response."
        ),
    ]
    reachable: Annotated[
        bool,
        described_field(
            "Reachable for this operational reconciliation snapshot response."
        ),
    ]
    total_contexts: Annotated[
        int,
        described_field(
            "Total contexts for this operational reconciliation snapshot response."
        ),
    ]
    temporal_state_count: Annotated[
        int,
        described_field(
            "Temporal state count for this operational reconciliation snapshot response."
        ),
    ]
    missing_temporal_states: Annotated[
        int,
        described_field(
            "Missing temporal states for this operational reconciliation snapshot response."
        ),
    ]
    backfill_complete: Annotated[
        bool,
        described_field(
            "Backfill complete for this operational reconciliation snapshot response."
        ),
    ]
    total_plans: Annotated[
        int,
        described_field(
            "Total plans for this operational reconciliation snapshot response."
        ),
    ]
    pending_review_plans: Annotated[
        int,
        described_field(
            "Pending review plans for this operational reconciliation snapshot response."
        ),
    ]
    total_results: Annotated[
        int,
        described_field(
            "Total results for this operational reconciliation snapshot response."
        ),
    ]
    partial_apply_results: Annotated[
        int,
        described_field(
            "Partial apply results for this operational reconciliation snapshot response."
        ),
    ]
    failed_results: Annotated[
        int,
        described_field(
            "Failed results for this operational reconciliation snapshot response."
        ),
    ]
    open_conflicts: Annotated[
        int,
        described_field(
            "Open conflicts for this operational reconciliation snapshot response."
        ),
    ]
    reviewing_conflicts: Annotated[
        int,
        described_field(
            "Reviewing conflicts for this operational reconciliation snapshot response."
        ),
    ]
    hard_delete_results: Annotated[
        int,
        described_field(
            "Hard delete results for this operational reconciliation snapshot response."
        ),
    ]
    latest_failure_code: Annotated[
        str | None,
        described_field(
            "Latest failure code for this operational reconciliation snapshot response."
        ),
    ]
    latest_failure_at: Annotated[
        AwareTimestamp | None,
        described_field(
            "Latest failure at for this operational reconciliation snapshot response."
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
