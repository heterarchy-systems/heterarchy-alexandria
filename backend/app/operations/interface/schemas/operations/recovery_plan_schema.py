"""HTTP schemas for recovery dry-run planning."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

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
    schema_dict_default,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp


class RecoveryPlanRequestSchema(StrictSchemaModel):
    """Request schema for recovery dry-run planning."""

    trigger: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Trigger for this recovery plan request."),
    ] = "manual"
    actor: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Actor for this recovery plan request."),
    ] = "operator"
    idempotency_key: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        Field(description="Idempotency key for this recovery plan request."),
    ] = None
    parent_run_id: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        Field(description="Parent run identifier for this recovery plan request."),
    ] = None
    expected_plan_hash: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=64, max_length=64),
        Field(
            description="Exact plan hash admitted by a prior dry-run; a mismatch fails "
            "the apply fence closed."
        ),
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
            expected_plan_hash=self.expected_plan_hash,
        )


class RecoverySourceSnapshotResponse(StrictSchemaModel):
    """Source preservation preflight response."""

    vault_path: Annotated[
        str, Field(description="Vault path for this recovery source snapshot response.")
    ]
    alexandria_root: Annotated[
        str,
        Field(
            description="Alexandria root for this recovery source snapshot response."
        ),
    ]
    managed_markdown_count: Annotated[
        int,
        Field(
            description="Managed markdown count for this recovery source snapshot response."
        ),
    ]
    representative_path: Annotated[
        str | None,
        Field(
            description="Representative path for this recovery source snapshot response."
        ),
    ]
    representative_sha256: Annotated[
        str | None,
        Field(
            description="Representative SHA-256 for this recovery source snapshot response."
        ),
    ]
    disk_free_bytes: Annotated[
        int | None,
        Field(
            description="Disk free bytes for this recovery source snapshot response."
        ),
    ]
    access_error: Annotated[
        str | None,
        Field(description="Access error for this recovery source snapshot response."),
    ] = None
    markdown_manifest: Annotated[
        dict[str, str],
        Field(
            description="Markdown manifest for this recovery source snapshot response."
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

    code: Annotated[
        str, Field(description="Code for this recovery plan step response.")
    ]
    title: Annotated[
        str, Field(description="Title for this recovery plan step response.")
    ]
    mutates_state: Annotated[
        bool, Field(description="Mutates state for this recovery plan step response.")
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
        str, Field(description="Stable identifier for this recovery plan response.")
    ]
    parent_run_id: Annotated[
        str | None,
        Field(description="Parent run identifier for this recovery plan response."),
    ]
    idempotency_key: Annotated[
        str, Field(description="Idempotency key for this recovery plan response.")
    ]
    trigger: Annotated[
        str, Field(description="Trigger for this recovery plan response.")
    ]
    actor: Annotated[str, Field(description="Actor for this recovery plan response.")]
    status: Annotated[
        OperationalReadinessStatus,
        Field(description="Status for this recovery plan response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        Field(description="Creation timestamp for this recovery plan response."),
    ]
    dry_run: Annotated[
        bool, Field(description="Dry run for this recovery plan response.")
    ]
    automatic_execution_allowed: Annotated[
        bool,
        Field(
            description="Automatic execution allowed for this recovery plan response."
        ),
    ]
    diagnosis: Annotated[
        list[str], Field(description="Diagnosis for this recovery plan response.")
    ] = schema_list_default()
    blocked_reasons: Annotated[
        list[str], Field(description="Blocked reasons for this recovery plan response.")
    ] = schema_list_default()
    source_snapshot: Annotated[
        RecoverySourceSnapshotResponse,
        Field(description="Source snapshot for this recovery plan response."),
    ]
    steps: Annotated[
        list[RecoveryPlanStepResponse],
        Field(description="Steps for this recovery plan response."),
    ] = schema_list_default()
    plan_hash: Annotated[
        str,
        Field(
            description="Deterministic hash over planned steps, diagnosis, and the source "
            "manifest; required unchanged by the apply fence."
        ),
    ]
    error_note_repairs: Annotated[
        list[str],
        Field(
            description="Bounded index-error note paths planned for note-local repair."
        ),
    ] = schema_list_default()
    estimated_reindex_scope: Annotated[
        dict[str, int | str | None],
        Field(description="Estimated reindex scope for this recovery plan response."),
    ]
    service_impact: Annotated[
        list[str], Field(description="Service impact for this recovery plan response.")
    ] = schema_list_default()
    next_actions: Annotated[
        list[str], Field(description="Next actions for this recovery plan response.")
    ] = schema_list_default()
    readiness: Annotated[
        OperationalReadinessSnapshotResponse,
        Field(description="Readiness for this recovery plan response."),
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this recovery plan response.")
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
            plan_hash=plan.plan_hash,
            error_note_repairs=list(plan.error_note_repairs),
            estimated_reindex_scope=dict(plan.estimated_reindex_scope),
            service_impact=list(plan.service_impact),
            next_actions=list(plan.next_actions),
            readiness=OperationalReadinessSnapshotResponse.from_entity(plan.readiness),
            warnings=list(plan.warnings),
        )
