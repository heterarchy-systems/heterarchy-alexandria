"""Operational readiness detail schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.operations.application.readiness.policy.operational_overall_readiness import (
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
    OperationalCompileReceiptSnapshotResponse,
    OperationalDatabaseSnapshotResponse,
    OperationalGraphSnapshotResponse,
    OperationalRagSnapshotResponse,
    OperationalReconciliationSnapshotResponse,
    OperationalVaultSnapshotResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.schemas.datetime_schemas import AwareTimestamp


class OperationalDataIntegrityWarningResponse(StrictSchemaModel):
    """One aggregated canonical-data warning."""

    code: Annotated[
        OperationalDataIntegrityWarningCode,
        Field(description="Code for this operational data integrity warning response."),
    ]
    count: Annotated[
        int,
        Field(
            description="Count for this operational data integrity warning response."
        ),
    ]
    note_paths: Annotated[
        list[str],
        Field(
            description="Note paths for this operational data integrity warning response."
        ),
    ] = schema_list_default()
    fields: Annotated[
        list[str],
        Field(
            description="Fields for this operational data integrity warning response."
        ),
    ] = schema_list_default()


class OperationalDataIntegritySnapshotResponse(StrictSchemaModel):
    """Canonical managed-note integrity independent of infrastructure."""

    status: Annotated[
        OperationalDataIntegrityStatus,
        Field(
            description="Status for this operational data integrity snapshot response."
        ),
    ] = OperationalDataIntegrityStatus.NOT_CHECKED
    scanned_notes: Annotated[
        int,
        Field(
            description="Scanned notes for this operational data integrity snapshot response."
        ),
    ] = 0
    warnings: Annotated[
        list[OperationalDataIntegrityWarningResponse],
        Field(
            description="Warnings for this operational data integrity snapshot response."
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
        Field(description="Status for this operational readiness snapshot response."),
    ]
    overall_status: Annotated[
        OperationalOverallStatus,
        Field(
            description="Overall status for this operational readiness snapshot response."
        ),
    ]
    ready: Annotated[
        bool,
        Field(description="Ready for this operational readiness snapshot response."),
    ]
    checked_at: Annotated[
        AwareTimestamp,
        Field(
            description="Checked at for this operational readiness snapshot response."
        ),
    ]
    duration_ms: Annotated[
        int,
        Field(
            description="Duration ms for this operational readiness snapshot response."
        ),
    ]
    vault: Annotated[
        OperationalVaultSnapshotResponse,
        Field(description="Vault for this operational readiness snapshot response."),
    ]
    database: Annotated[
        OperationalDatabaseSnapshotResponse,
        Field(description="Database for this operational readiness snapshot response."),
    ]
    rag: Annotated[
        OperationalRagSnapshotResponse,
        Field(description="RAG for this operational readiness snapshot response."),
    ]
    reconciliation: Annotated[
        OperationalReconciliationSnapshotResponse,
        Field(
            description="Reconciliation for this operational readiness snapshot response."
        ),
    ]
    runtime: Annotated[
        OperationalRuntimeProvenanceResponse,
        Field(
            description="Runtime provenance for this operational readiness response."
        ),
    ]
    retrieval_canary: Annotated[
        OperationalRetrievalCanarySnapshotResponse,
        Field(
            description="Real retrieval path canaries for this operational readiness response."
        ),
    ]
    projection_integrity: Annotated[
        ContextProjectionIntegritySnapshotResponse,
        Field(
            description="Persisted full Obsidian-to-Context projection integrity state."
        ),
    ]
    compile_receipt: Annotated[
        OperationalCompileReceiptSnapshotResponse,
        Field(
            description="Latest knowledge compile receipt evidence for this snapshot."
        ),
    ]
    graph: Annotated[
        OperationalGraphSnapshotResponse,
        Field(description="Graph projection evidence for this readiness snapshot."),
    ]
    active_recovery_run_id: Annotated[
        str | None,
        Field(
            description="Active recovery run identifier for this operational readiness snapshot response."
        ),
    ] = None
    last_successful_recovery_run_id: Annotated[
        str | None,
        Field(
            description="Last successful recovery run identifier for this operational readiness snapshot response."
        ),
    ] = None
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this operational readiness snapshot response."),
    ] = schema_list_default()
    blockers: Annotated[
        list[str],
        Field(description="Blockers for this operational readiness snapshot response."),
    ] = schema_list_default()
    next_actions: Annotated[
        list[str],
        Field(
            description="Next actions for this operational readiness snapshot response."
        ),
    ] = schema_list_default()
    data_integrity: Annotated[
        OperationalDataIntegritySnapshotResponse,
        Field(
            description="Data integrity for this operational readiness snapshot response."
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
            compile_receipt=OperationalCompileReceiptSnapshotResponse.from_entity(
                snapshot.compile_receipt
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
