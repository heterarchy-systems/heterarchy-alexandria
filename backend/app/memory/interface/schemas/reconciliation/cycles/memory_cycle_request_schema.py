"""Strict HTTP/MCP schemas for the high-level memory-cycle request."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationInfo, field_validator

from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCycleOperation
from app.shared.schemas.common_schemas import StrictRootSchemaModel, StrictSchemaModel

_IdempotencyKey = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=512),
]


_Sha256 = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-f]{64}$",
    ),
]


class _MemoryCycleRequestFields(StrictSchemaModel):
    """Shared bounded source/window fields for both discriminated operations."""

    project: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=255),
        Field(description="Required project identity for the cycle source window."),
    ]
    workspace_id: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=255),
        Field(description="Optional workspace identity for the cycle source window."),
    ] = None
    scope: Annotated[
        ContextScope,
        Field(description="Project scope for the cycle source window."),
    ] = ContextScope.PROJECT
    window_start: Annotated[
        datetime,
        Field(description="Inclusive timezone-aware source window start."),
    ]
    window_end: Annotated[
        datetime,
        Field(description="Inclusive timezone-aware source window end."),
    ]
    idempotency_key: Annotated[
        _IdempotencyKey,
        Field(description="Stable logical identity used for cycle replay fencing."),
    ]
    max_contexts: Annotated[
        int,
        Field(description="Maximum bounded Context candidates to scan.", ge=1, le=100),
    ] = 100

    @field_validator("window_start", "window_end")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        """Reject local/naive timestamps at the public boundary."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("memory-cycle window timestamps must be timezone-aware")
        return value

    @field_validator("window_end")
    @classmethod
    def require_ordered_window(
        cls,
        value: datetime,
        info: ValidationInfo,
    ) -> datetime:
        """Reject an end timestamp that precedes the start timestamp."""
        start = info.data.get("window_start")
        if isinstance(start, datetime) and value < start:
            raise ValueError("memory-cycle window_end must not precede window_start")
        return value

    @field_validator("scope")
    @classmethod
    def require_project_scope(cls, value: ContextScope) -> ContextScope:
        """Keep the public composite aligned with project CURRENT authority."""
        if ContextScope(value) is not ContextScope.PROJECT:
            raise ValueError("memory-cycle scope must be PROJECT")
        return value


class MemoryCycleDryRunRequestSchema(_MemoryCycleRequestFields):
    """Discriminated write-free memory-cycle planning request."""

    operation: Literal["dry_run"] = "dry_run"

    def to_command(self) -> MemoryCycleRequest:
        """Convert the boundary request to the typed application command."""
        return MemoryCycleRequest(
            operation=MemoryCycleOperation.DRY_RUN,
            project=self.project,
            workspace_id=self.workspace_id,
            scope=ContextScope(self.scope),
            window_start=self.window_start,
            window_end=self.window_end,
            idempotency_key=self.idempotency_key,
            max_contexts=self.max_contexts,
        )


class MemoryCycleApplyRequestSchema(_MemoryCycleRequestFields):
    """Discriminated fenced memory-cycle apply request."""

    operation: Literal["apply"] = "apply"
    expected_plan_hash: Annotated[
        _Sha256,
        Field(description="Exact semantic plan hash admitted by a prior dry-run."),
    ]

    def to_command(self) -> MemoryCycleRequest:
        """Convert the boundary request to the typed application command."""
        return MemoryCycleRequest(
            operation=MemoryCycleOperation.APPLY,
            project=self.project,
            workspace_id=self.workspace_id,
            scope=ContextScope(self.scope),
            window_start=self.window_start,
            window_end=self.window_end,
            idempotency_key=self.idempotency_key,
            max_contexts=self.max_contexts,
            expected_plan_hash=self.expected_plan_hash,
        )


MemoryCycleRequestSchema = Annotated[
    MemoryCycleDryRunRequestSchema | MemoryCycleApplyRequestSchema,
    Field(discriminator="operation"),
]


class MemoryCycleRequestBody(StrictRootSchemaModel[MemoryCycleRequestSchema]):
    """Strict JSON-mode HTTP body wrapper for the cycle operation."""
