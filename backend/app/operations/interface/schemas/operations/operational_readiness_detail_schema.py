"""Operational readiness detail schema contracts."""

from __future__ import annotations

from typing import Annotated

from app.operations.application.readiness.operational_overall_readiness import (
    overall_readiness_status,
)
from app.operations.domain.entities.operational_data_integrity import (
    OperationalDataIntegritySnapshot,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.event_enum.operational_data_integrity_enums import (
    OperationalDataIntegrityStatus,
    OperationalDataIntegrityWarningCode,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalOverallStatus,
    OperationalReadinessStatus,
)
from app.operations.interface.schemas.operations.operational_memory_path_schema import (
    ContextProjectionIntegritySnapshotResponse,
    OperationalRetrievalCanarySnapshotResponse,
    OperationalRuntimeProvenanceResponse,
)
from app.operations.interface.schemas.operations.operational_readiness_schema import (
    OperationalDatabaseSnapshotResponse,
    OperationalGraphSnapshotResponse,
    OperationalRagSnapshotResponse,
    OperationalReconciliationSnapshotResponse,
    OperationalVaultSnapshotResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp


class OperationalDataIntegrityWarningResponse(StrictSchemaModel):
    """One aggregated canonical-data warning."""

    code: Annotated[
        OperationalDataIntegrityWarningCode,
        described_field("Code for this operational data integrity warning response."),
    ]
    count: Annotated[
        int,
        described_field("Count for this operational data integrity warning response."),
    ]
    note_paths: Annotated[
        list[str],
        described_field(
            "Note paths for this operational data integrity warning response."
        ),
    ] = schema_list_default()
    fields: Annotated[
        list[str],
        described_field("Fields for this operational data integrity warning response."),
    ] = schema_list_default()


class OperationalDataIntegritySnapshotResponse(StrictSchemaModel):
    """Canonical managed-note integrity independent of infrastructure."""

    status: Annotated[
        OperationalDataIntegrityStatus,
        described_field(
            "Status for this operational data integrity snapshot response."
        ),
    ] = OperationalDataIntegrityStatus.NOT_CHECKED
    scanned_notes: Annotated[
        int,
        described_field(
            "Scanned notes for this operational data integrity snapshot response."
        ),
    ] = 0
    warnings: Annotated[
        list[OperationalDataIntegrityWarningResponse],
        described_field(
            "Warnings for this operational data integrity snapshot response."
        ),
    ] = schema_list_default()

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalDataIntegritySnapshot,
    ) -> OperationalDataIntegritySnapshotResponse:
        """Map the internal integrity snapshot to the HTTP contract.

        Args:
            snapshot: Internal data-integrity diagnostic snapshot.

        Returns:
            HTTP data-integrity response.
        """
        return cls(
            status=snapshot.status,
            scanned_notes=snapshot.scanned_notes,
            warnings=[
                OperationalDataIntegrityWarningResponse(
                    code=warning.code,
                    count=warning.count,
                    note_paths=list(warning.note_paths),
                    fields=list(warning.fields),
                )
                for warning in snapshot.warnings
            ],
        )


class OperationalReadinessSnapshotResponse(StrictSchemaModel):
    """Read-only operational readiness response."""

    status: Annotated[
        OperationalReadinessStatus,
        described_field("Status for this operational readiness snapshot response."),
    ]
    overall_status: Annotated[
        OperationalOverallStatus,
        described_field(
            "Overall status for this operational readiness snapshot response."
        ),
    ]
    ready: Annotated[
        bool, described_field("Ready for this operational readiness snapshot response.")
    ]
    checked_at: Annotated[
        AwareTimestamp,
        described_field("Checked at for this operational readiness snapshot response."),
    ]
    duration_ms: Annotated[
        int,
        described_field(
            "Duration ms for this operational readiness snapshot response."
        ),
    ]
    vault: Annotated[
        OperationalVaultSnapshotResponse,
        described_field("Vault for this operational readiness snapshot response."),
    ]
    database: Annotated[
        OperationalDatabaseSnapshotResponse,
        described_field("Database for this operational readiness snapshot response."),
    ]
    rag: Annotated[
        OperationalRagSnapshotResponse,
        described_field("RAG for this operational readiness snapshot response."),
    ]
    reconciliation: Annotated[
        OperationalReconciliationSnapshotResponse,
        described_field(
            "Reconciliation for this operational readiness snapshot response."
        ),
    ]
    runtime: Annotated[
        OperationalRuntimeProvenanceResponse,
        described_field("Runtime provenance for this operational readiness response."),
    ]
    retrieval_canary: Annotated[
        OperationalRetrievalCanarySnapshotResponse,
        described_field(
            "Real retrieval path canaries for this operational readiness response."
        ),
    ]
    projection_integrity: Annotated[
        ContextProjectionIntegritySnapshotResponse,
        described_field(
            "Persisted full Obsidian-to-Context projection integrity state."
        ),
    ]
    graph: Annotated[
        OperationalGraphSnapshotResponse,
        described_field("Graph projection evidence for this readiness snapshot."),
    ]
    active_recovery_run_id: Annotated[
        str | None,
        described_field(
            "Active recovery run identifier for this operational readiness snapshot response."
        ),
    ] = None
    last_successful_recovery_run_id: Annotated[
        str | None,
        described_field(
            "Last successful recovery run identifier for this operational readiness snapshot response."
        ),
    ] = None
    warnings: Annotated[
        list[str],
        described_field("Warnings for this operational readiness snapshot response."),
    ] = schema_list_default()
    blockers: Annotated[
        list[str],
        described_field("Blockers for this operational readiness snapshot response."),
    ] = schema_list_default()
    next_actions: Annotated[
        list[str],
        described_field(
            "Next actions for this operational readiness snapshot response."
        ),
    ] = schema_list_default()
    data_integrity: Annotated[
        OperationalDataIntegritySnapshotResponse,
        described_field(
            "Data integrity for this operational readiness snapshot response."
        ),
    ] = OperationalDataIntegritySnapshotResponse()

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalReadinessSnapshot,
    ) -> OperationalReadinessSnapshotResponse:
        """Create response schema from read model.

        Args:
            snapshot: Operational readiness read model.

        Returns:
            Operational readiness response schema.
        """
        return cls(
            status=snapshot.status,
            overall_status=overall_readiness_status(snapshot),
            ready=snapshot.ready,
            checked_at=snapshot.checked_at,
            duration_ms=snapshot.duration_ms,
            vault=OperationalVaultSnapshotResponse.from_entity(snapshot.vault),
            database=OperationalDatabaseSnapshotResponse.from_entity(snapshot.database),
            rag=OperationalRagSnapshotResponse.from_entity(snapshot.rag),
            reconciliation=OperationalReconciliationSnapshotResponse.from_entity(
                snapshot.reconciliation
            ),
            runtime=OperationalRuntimeProvenanceResponse.from_entity(snapshot.runtime),
            retrieval_canary=OperationalRetrievalCanarySnapshotResponse.from_entity(
                snapshot.retrieval_canary
            ),
            projection_integrity=ContextProjectionIntegritySnapshotResponse.from_entity(
                snapshot.projection_integrity
            ),
            graph=OperationalGraphSnapshotResponse.from_entity(snapshot.graph),
            active_recovery_run_id=snapshot.active_recovery_run_id,
            last_successful_recovery_run_id=snapshot.last_successful_recovery_run_id,
            warnings=list(snapshot.warnings),
            blockers=list(snapshot.blockers),
            next_actions=list(snapshot.next_actions),
            data_integrity=OperationalDataIntegritySnapshotResponse.from_entity(
                snapshot.data_integrity
            ),
        )
