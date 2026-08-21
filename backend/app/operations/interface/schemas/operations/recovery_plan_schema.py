"""HTTP schemas for recovery dry-run planning."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlan,
    RecoveryPlanStep,
    RecoverySourceSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.operations.interface.schemas.operations.operational_readiness_detail_schema import (
    OperationalReadinessSnapshotResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_dict_default,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp


class RecoveryPlanRequestSchema(StrictSchemaModel):
    """Request schema for recovery dry-run planning."""

    trigger: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Trigger for this recovery plan request."),
    ] = "manual"
    actor: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Actor for this recovery plan request."),
    ] = "operator"
    idempotency_key: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        described_field("Idempotency key for this recovery plan request."),
    ] = None
    parent_run_id: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        described_field("Parent run identifier for this recovery plan request."),
    ] = None

    def to_contract(self) -> RecoveryPlanRequest:
        """Convert schema to application request contract.

        Returns:
            Recovery plan request contract.
        """
        return RecoveryPlanRequest(
            trigger=self.trigger,
            actor=self.actor,
            idempotency_key=self.idempotency_key,
            parent_run_id=self.parent_run_id,
        )


class RecoverySourceSnapshotResponse(StrictSchemaModel):
    """Source preservation preflight response."""

    vault_path: Annotated[
        str, described_field("Vault path for this recovery source snapshot response.")
    ]
    alexandria_root: Annotated[
        str,
        described_field("Alexandria root for this recovery source snapshot response."),
    ]
    managed_markdown_count: Annotated[
        int,
        described_field(
            "Managed markdown count for this recovery source snapshot response."
        ),
    ]
    representative_path: Annotated[
        str | None,
        described_field(
            "Representative path for this recovery source snapshot response."
        ),
    ]
    representative_sha256: Annotated[
        str | None,
        described_field(
            "Representative SHA-256 for this recovery source snapshot response."
        ),
    ]
    disk_free_bytes: Annotated[
        int | None,
        described_field("Disk free bytes for this recovery source snapshot response."),
    ]
    access_error: Annotated[
        str | None,
        described_field("Access error for this recovery source snapshot response."),
    ] = None
    markdown_manifest: Annotated[
        dict[str, str],
        described_field(
            "Markdown manifest for this recovery source snapshot response."
        ),
    ] = schema_dict_default()

    @classmethod
    def from_entity(
        cls,
        snapshot: RecoverySourceSnapshot,
    ) -> RecoverySourceSnapshotResponse:
        """Create response schema from read model.

        Args:
            snapshot: Source snapshot read model.

        Returns:
            Source snapshot response schema.
        """
        return cls(
            vault_path=snapshot.vault_path,
            alexandria_root=snapshot.alexandria_root,
            managed_markdown_count=snapshot.managed_markdown_count,
            representative_path=snapshot.representative_path,
            representative_sha256=snapshot.representative_sha256,
            disk_free_bytes=snapshot.disk_free_bytes,
            access_error=snapshot.access_error,
            markdown_manifest=dict(snapshot.markdown_manifest),
        )


class RecoveryPlanStepResponse(StrictSchemaModel):
    """Planned recovery step response."""

    code: Annotated[str, described_field("Code for this recovery plan step response.")]
    title: Annotated[
        str, described_field("Title for this recovery plan step response.")
    ]
    mutates_state: Annotated[
        bool, described_field("Mutates state for this recovery plan step response.")
    ]

    @classmethod
    def from_entity(cls, step: RecoveryPlanStep) -> RecoveryPlanStepResponse:
        """Create response schema from read model.

        Args:
            step: Recovery step read model.

        Returns:
            Recovery step response schema.
        """
        return cls(code=step.code, title=step.title, mutates_state=step.mutates_state)


class RecoveryPlanResponse(StrictSchemaModel):
    """Recovery dry-run plan response."""

    id: Annotated[
        str, described_field("Stable identifier for this recovery plan response.")
    ]
    parent_run_id: Annotated[
        str | None,
        described_field("Parent run identifier for this recovery plan response."),
    ]
    idempotency_key: Annotated[
        str, described_field("Idempotency key for this recovery plan response.")
    ]
    trigger: Annotated[str, described_field("Trigger for this recovery plan response.")]
    actor: Annotated[str, described_field("Actor for this recovery plan response.")]
    status: Annotated[
        OperationalReadinessStatus,
        described_field("Status for this recovery plan response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this recovery plan response."),
    ]
    dry_run: Annotated[
        bool, described_field("Dry run for this recovery plan response.")
    ]
    automatic_execution_allowed: Annotated[
        bool,
        described_field("Automatic execution allowed for this recovery plan response."),
    ]
    diagnosis: Annotated[
        list[str], described_field("Diagnosis for this recovery plan response.")
    ] = schema_list_default()
    blocked_reasons: Annotated[
        list[str], described_field("Blocked reasons for this recovery plan response.")
    ] = schema_list_default()
    source_snapshot: Annotated[
        RecoverySourceSnapshotResponse,
        described_field("Source snapshot for this recovery plan response."),
    ]
    steps: Annotated[
        list[RecoveryPlanStepResponse],
        described_field("Steps for this recovery plan response."),
    ] = schema_list_default()
    estimated_reindex_scope: Annotated[
        dict[str, int | str | None],
        described_field("Estimated reindex scope for this recovery plan response."),
    ]
    service_impact: Annotated[
        list[str], described_field("Service impact for this recovery plan response.")
    ] = schema_list_default()
    next_actions: Annotated[
        list[str], described_field("Next actions for this recovery plan response.")
    ] = schema_list_default()
    readiness: Annotated[
        OperationalReadinessSnapshotResponse,
        described_field("Readiness for this recovery plan response."),
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this recovery plan response.")
    ] = schema_list_default()

    @classmethod
    def from_entity(cls, plan: RecoveryPlan) -> RecoveryPlanResponse:
        """Create response schema from read model.

        Args:
            plan: Recovery dry-run plan.

        Returns:
            Recovery plan response schema.
        """
        return cls(
            id=plan.id,
            parent_run_id=plan.parent_run_id,
            idempotency_key=plan.idempotency_key,
            trigger=plan.trigger,
            actor=plan.actor,
            status=plan.status,
            created_at=plan.created_at,
            dry_run=plan.dry_run,
            automatic_execution_allowed=plan.automatic_execution_allowed,
            diagnosis=list(plan.diagnosis),
            blocked_reasons=list(plan.blocked_reasons),
            source_snapshot=RecoverySourceSnapshotResponse.from_entity(
                plan.source_snapshot
            ),
            steps=[RecoveryPlanStepResponse.from_entity(step) for step in plan.steps],
            estimated_reindex_scope=dict(plan.estimated_reindex_scope),
            service_impact=list(plan.service_impact),
            next_actions=list(plan.next_actions),
            readiness=OperationalReadinessSnapshotResponse.from_entity(plan.readiness),
            warnings=list(plan.warnings),
        )
