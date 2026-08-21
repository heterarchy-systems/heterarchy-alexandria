"""Strict HTTP request schema for existing-memory reconciliation scans."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.contracts.memory_existing_reconciliation_contracts import (
    ExistingMemoryReconciliationRequest,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from pydantic import StringConstraints, field_validator


class ExistingMemoryReconciliationHttpRequest(StrictSchemaModel):
    """Bounded filters for dry-run or apply existing-memory reconciliation."""

    project: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=255),
        described_field(
            "Project for this existing memory reconciliation HTTP request."
        ),
    ] = None
    scope: Annotated[
        ContextScope | None,
        described_field("Scope for this existing memory reconciliation HTTP request."),
    ] = None
    include_archived: Annotated[
        bool,
        described_field(
            "Include archived for this existing memory reconciliation HTTP request."
        ),
    ] = False
    max_contexts: Annotated[
        int,
        described_field(
            "Max contexts for this existing memory reconciliation HTTP request.",
            ge=1,
            le=10000,
        ),
    ] = 500
    batch_size: Annotated[
        int,
        described_field(
            "Batch size for this existing memory reconciliation HTTP request.",
            ge=1,
            le=500,
        ),
    ] = 100
    recall_limit: Annotated[
        int,
        described_field(
            "Recall limit for this existing memory reconciliation HTTP request.",
            ge=1,
            le=100,
        ),
    ] = 20

    @field_validator("project")
    @classmethod
    def normalize_optional_project(cls, value: str | None) -> str | None:
        """Normalize optional project identity without inventing one.

        Args:
            value: Value.

        Returns:
            str | None: Operation result.
        """
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def to_contract(self) -> ExistingMemoryReconciliationRequest:
        """Convert validated HTTP input into the internal frozen contract.

        Returns:
            ExistingMemoryReconciliationRequest: Operation result.
        """
        return ExistingMemoryReconciliationRequest(
            project=self.project,
            scope=self.scope,
            include_archived=self.include_archived,
            max_contexts=self.max_contexts,
            batch_size=self.batch_size,
            recall_limit=self.recall_limit,
        )
