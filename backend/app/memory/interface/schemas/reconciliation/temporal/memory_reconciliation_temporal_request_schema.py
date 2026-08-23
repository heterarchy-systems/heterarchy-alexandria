"""Strict temporal recall request schema for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator

from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagStrategy,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryTemporalRecallMode,
)
from app.memory.interface.schemas.reconciliation.reconciliation_string_types import (
    ReconciliationScopeFilterText,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.types_convert_utils import enum_value


class MemoryTemporalRecallHttpRequest(StrictSchemaModel):
    """Recall Contexts through current, historical, or all temporal state."""

    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=10000),
        described_field("Query for this memory temporal recall HTTP request."),
    ]
    mode: Annotated[
        MemoryTemporalRecallMode,
        described_field("Mode for this memory temporal recall HTTP request."),
    ] = MemoryTemporalRecallMode.CURRENT
    as_of: Annotated[
        AwareTimestamp | None,
        described_field("As of for this memory temporal recall HTTP request."),
    ] = None
    strategy: Annotated[
        RagStrategy,
        described_field("Strategy for this memory temporal recall HTTP request."),
    ] = RagStrategy.HYBRID
    limit: Annotated[
        int,
        described_field(
            "Limit for this memory temporal recall HTTP request.", ge=1, le=100
        ),
    ] = 5
    project: Annotated[
        ReconciliationScopeFilterText,
        described_field("Project for this memory temporal recall HTTP request."),
    ] = None
    kind: Annotated[
        ContextKind | None,
        described_field("Kind for this memory temporal recall HTTP request."),
    ] = None
    include_scopes: Annotated[
        list[ContextScope],
        described_field("Include scopes for this memory temporal recall HTTP request."),
    ] = schema_list_default()
    workspace_id: Annotated[
        ReconciliationScopeFilterText,
        described_field(
            "Workspace identifier for this memory temporal recall HTTP request."
        ),
    ] = None
    agent_id: Annotated[
        ReconciliationScopeFilterText,
        described_field(
            "Agent identifier for this memory temporal recall HTTP request."
        ),
    ] = None
    user_id: Annotated[
        ReconciliationScopeFilterText,
        described_field(
            "User identifier for this memory temporal recall HTTP request."
        ),
    ] = None
    session_id: Annotated[
        ReconciliationScopeFilterText,
        described_field(
            "Session identifier for this memory temporal recall HTTP request."
        ),
    ] = None
    include_lifecycle_statuses: Annotated[
        list[ContextRecallLifecycleStatus],
        described_field(
            "Include lifecycle statuses for this memory temporal recall HTTP request."
        ),
    ] = schema_list_default()

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        """Normalize and require a concrete recall query.

        Args:
            value: Value.

        Returns:
            str: Operation result.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("temporal recall query is required")
        return normalized

    @field_validator(
        "project",
        "workspace_id",
        "agent_id",
        "user_id",
        "session_id",
    )
    @classmethod
    def normalize_temporal_identity(cls, value: str | None) -> str | None:
        """Normalize optional temporal recall identities.

        Args:
            value: Value.

        Returns:
            str | None: Operation result.
        """
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def to_contract(self) -> MemoryTemporalRecallRequest:
        """Convert the HTTP request into the temporal recall application contract.

        Returns:
            MemoryTemporalRecallRequest: Operation result.
        """
        return MemoryTemporalRecallRequest(
            query=self.query,
            mode=enum_value(self.mode, MemoryTemporalRecallMode, "mode"),
            as_of=self.as_of,
            strategy=enum_value(self.strategy, RagStrategy, "strategy"),
            limit=self.limit,
            project=self.project,
            kind=(
                None
                if self.kind is None
                else enum_value(self.kind, ContextKind, "kind")
            ),
            include_scopes=tuple(
                enum_value(item, ContextScope, "include_scopes")
                for item in self.include_scopes
            ),
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            user_id=self.user_id,
            session_id=self.session_id,
            include_lifecycle_statuses=tuple(
                enum_value(
                    item,
                    ContextRecallLifecycleStatus,
                    "include_lifecycle_statuses",
                )
                for item in self.include_lifecycle_statuses
            ),
        )
