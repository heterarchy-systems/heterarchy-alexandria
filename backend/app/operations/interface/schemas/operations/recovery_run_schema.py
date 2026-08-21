"""HTTP schemas for PostgreSQL-native recovery run execution."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.domain.entities.recovery_run import (
    RecoveryRun,
    RecoveryRunStepResult,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
    RecoveryStepStatus,
)
from app.operations.interface.schemas.operations.recovery_plan_schema import (
    RecoveryPlanRequestSchema,
    RecoveryPlanStepResponse,
    RecoverySourceSnapshotResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_dict_default,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject


class RecoveryRunRequestSchema(RecoveryPlanRequestSchema):
    """Request schema for starting a recovery run."""

    def to_contract(self) -> RecoveryPlanRequest:
        """Convert schema to application request contract.

        Returns:
            Application recovery-plan request contract.
        """
        return RecoveryPlanRequest(
            trigger=self.trigger,
            actor=self.actor,
            idempotency_key=self.idempotency_key,
            parent_run_id=self.parent_run_id,
        )


class RecoveryRunRetryRequestSchema(RecoveryRunRequestSchema):
    """Request schema for retrying a recovery run."""

    trigger: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Trigger for this recovery run retry request."),
    ] = "retry"
    parent_run_id: None = None

    def to_contract(self) -> RecoveryPlanRequest:
        """Convert schema to application retry contract.

        Returns:
            Application retry request contract with no parent override.
        """
        return RecoveryPlanRequest(
            trigger=self.trigger,
            actor=self.actor,
            idempotency_key=self.idempotency_key,
            parent_run_id=None,
        )


class RecoveryRunStepResultResponse(StrictSchemaModel):
    """Recovery step execution result response."""

    code: Annotated[
        str, described_field("Code for this recovery run step result response.")
    ]
    status: Annotated[
        RecoveryStepStatus,
        described_field("Status for this recovery run step result response."),
    ]
    attempts: Annotated[
        int, described_field("Attempts for this recovery run step result response.")
    ]
    started_at: Annotated[
        AwareTimestamp | None,
        described_field("Started at for this recovery run step result response."),
    ]
    finished_at: Annotated[
        AwareTimestamp | None,
        described_field("Finished at for this recovery run step result response."),
    ]
    input_hash: Annotated[
        str, described_field("Input hash for this recovery run step result response.")
    ]
    result: Annotated[
        JSONObject,
        described_field("Result for this recovery run step result response."),
    ] = schema_dict_default()

    @classmethod
    def from_entity(
        cls,
        step: RecoveryRunStepResult,
    ) -> RecoveryRunStepResultResponse:
        """Create response schema from a recovery step result.

        Args:
            step: Recovery step domain result.

        Returns:
            Serialized recovery step response.
        """
        return cls(
            code=step.code,
            status=step.status,
            attempts=step.attempts,
            started_at=step.started_at,
            finished_at=step.finished_at,
            input_hash=step.input_hash,
            result=step.result,
        )


class RecoveryRunResponse(StrictSchemaModel):
    """Recovery run response."""

    id: Annotated[
        str, described_field("Stable identifier for this recovery run response.")
    ]
    parent_run_id: Annotated[
        str | None,
        described_field("Parent run identifier for this recovery run response."),
    ]
    idempotency_key: Annotated[
        str, described_field("Idempotency key for this recovery run response.")
    ]
    trigger: Annotated[str, described_field("Trigger for this recovery run response.")]
    actor: Annotated[str, described_field("Actor for this recovery run response.")]
    status: Annotated[
        RecoveryRunStatus, described_field("Status for this recovery run response.")
    ]
    current_step: Annotated[
        str | None, described_field("Current step for this recovery run response.")
    ]
    started_at: Annotated[
        AwareTimestamp, described_field("Started at for this recovery run response.")
    ]
    updated_at: Annotated[
        AwareTimestamp,
        described_field("Last-update timestamp for this recovery run response."),
    ]
    finished_at: Annotated[
        AwareTimestamp | None,
        described_field("Finished at for this recovery run response."),
    ]
    source_snapshot: Annotated[
        RecoverySourceSnapshotResponse,
        described_field("Source snapshot for this recovery run response."),
    ]
    diagnosis: Annotated[
        list[str], described_field("Diagnosis for this recovery run response.")
    ] = schema_list_default()
    planned_steps: Annotated[
        list[RecoveryPlanStepResponse],
        described_field("Planned steps for this recovery run response."),
    ] = schema_list_default()
    step_results: Annotated[
        list[RecoveryRunStepResultResponse],
        described_field("Step results for this recovery run response."),
    ] = schema_list_default()
    rebuild_results: Annotated[
        JSONObject, described_field("Rebuild results for this recovery run response.")
    ] = schema_dict_default()
    verification_results: Annotated[
        JSONObject,
        described_field("Verification results for this recovery run response."),
    ] = schema_dict_default()
    error_code: Annotated[
        str | None, described_field("Error code for this recovery run response.")
    ]
    error_summary: Annotated[
        str | None, described_field("Error summary for this recovery run response.")
    ]
    next_actions: Annotated[
        list[str], described_field("Next actions for this recovery run response.")
    ] = schema_list_default()
    manifest_path: Annotated[
        str, described_field("Manifest path for this recovery run response.")
    ]

    @classmethod
    def from_entity(cls, run: RecoveryRun) -> RecoveryRunResponse:
        """Create response schema from a recovery run.

        Args:
            run: Recovery run domain entity.

        Returns:
            Serialized recovery run response.
        """
        return cls(
            id=run.id,
            parent_run_id=run.parent_run_id,
            idempotency_key=run.idempotency_key,
            trigger=run.trigger,
            actor=run.actor,
            status=run.status,
            current_step=run.current_step,
            started_at=run.started_at,
            updated_at=run.updated_at,
            finished_at=run.finished_at,
            source_snapshot=RecoverySourceSnapshotResponse.from_entity(
                run.source_snapshot
            ),
            diagnosis=list(run.diagnosis),
            planned_steps=[
                RecoveryPlanStepResponse.from_entity(step) for step in run.planned_steps
            ],
            step_results=[
                RecoveryRunStepResultResponse.from_entity(step)
                for step in run.step_results
            ],
            rebuild_results=run.rebuild_results,
            verification_results=run.verification_results,
            error_code=run.error_code,
            error_summary=run.error_summary,
            next_actions=list(run.next_actions),
            manifest_path=run.manifest_path,
        )
