"""Strict candidate, preview, and apply request schemas for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryCandidateCreate,
    MemoryReconciliationPreviewRequest,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.interface.schemas.reconciliation.candidate.memory_reconciliation_claim_request_schema import (
    CanonicalClaimRequest,
    MemorySourceReferenceRequest,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.types_convert_utils import enum_value
from pydantic import StringConstraints, field_validator


class MemoryCandidateRequest(StrictSchemaModel):
    """Candidate memory submitted for reconciliation preview."""

    title: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=2000),
        described_field("Title for this memory candidate request."),
    ]
    body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=500000),
        described_field("Body for this memory candidate request."),
    ]
    scope: Annotated[
        ContextScope, described_field("Scope for this memory candidate request.")
    ]
    project: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=1000),
        described_field("Project for this memory candidate request."),
    ] = None
    workspace_id: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=1000),
        described_field("Workspace identifier for this memory candidate request."),
    ] = None
    agent_id: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=1000),
        described_field("Agent identifier for this memory candidate request."),
    ] = None
    user_id: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=1000),
        described_field("User identifier for this memory candidate request."),
    ] = None
    session_id: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=1000),
        described_field("Session identifier for this memory candidate request."),
    ] = None
    canonical_claims: Annotated[
        list[CanonicalClaimRequest],
        described_field("Canonical claims for this memory candidate request."),
    ] = schema_list_default()
    tags: Annotated[
        list[str],
        described_field("Tags for this memory candidate request.", max_length=200),
    ] = schema_list_default()
    source_refs: Annotated[
        list[MemorySourceReferenceRequest],
        described_field("Source refs for this memory candidate request."),
    ] = schema_list_default()
    recorded_at: Annotated[
        AwareTimestamp | None,
        described_field("Recorded at for this memory candidate request."),
    ] = None
    observed_at: Annotated[
        AwareTimestamp | None,
        described_field("Observed at for this memory candidate request."),
    ] = None
    valid_from: Annotated[
        AwareTimestamp | None,
        described_field("Valid from for this memory candidate request."),
    ] = None
    valid_to: Annotated[
        AwareTimestamp | None,
        described_field("Valid to for this memory candidate request."),
    ] = None
    requested_lifecycle: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=64),
        described_field("Requested lifecycle for this memory candidate request."),
    ] = "active"
    candidate_id: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=255),
        described_field("Candidate identifier for this memory candidate request."),
    ] = None
    source_identity: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=2000),
        described_field("Source identity for this memory candidate request."),
    ] = None

    @field_validator(
        "title",
        "body",
        "requested_lifecycle",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """Normalize required candidate text.

        Args:
            value: Value.

        Returns:
            str: Operation result.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("candidate text is required")
        return normalized

    @field_validator(
        "project",
        "workspace_id",
        "agent_id",
        "user_id",
        "session_id",
        "candidate_id",
        "source_identity",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Normalize optional identity text.

        Args:
            value: Value.

        Returns:
            str | None: Operation result.
        """
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        """Normalize and deduplicate request tags while preserving order.

        Args:
            values: Values.

        Returns:
            list[str]: Operation result.
        """
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    def to_contract(self) -> MemoryCandidateCreate:
        """Convert the request into the application input contract.

        Returns:
            MemoryCandidateCreate: Operation result.
        """
        scope = enum_value(self.scope, ContextScope, "scope")
        return MemoryCandidateCreate(
            title=self.title,
            body=self.body,
            scope=scope,
            project=self.project,
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            user_id=self.user_id,
            session_id=self.session_id,
            canonical_claims=tuple(
                item.to_entity(scope=scope, project=self.project)
                for item in self.canonical_claims
            ),
            tags=tuple(self.tags),
            source_refs=tuple(item.to_entity() for item in self.source_refs),
            recorded_at=self.recorded_at,
            observed_at=self.observed_at,
            valid_from=self.valid_from,
            valid_to=self.valid_to,
            requested_lifecycle=self.requested_lifecycle,
            candidate_id=self.candidate_id,
            source_identity=self.source_identity,
        )


class MemoryReconciliationPreviewHttpRequest(StrictSchemaModel):
    """Preview one memory candidate without canonical mutations."""

    candidate: Annotated[
        MemoryCandidateRequest,
        described_field(
            "Candidate for this memory reconciliation preview HTTP request."
        ),
    ]
    idempotency_key: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=128),
        described_field(
            "Idempotency key for this memory reconciliation preview HTTP request."
        ),
    ] = None
    recall_limit: Annotated[
        int,
        described_field(
            "Recall limit for this memory reconciliation preview HTTP request.",
            ge=1,
            le=100,
        ),
    ] = 20

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str | None) -> str | None:
        """Normalize an optional caller-controlled idempotency key.

        Args:
            value: Value.

        Returns:
            str | None: Operation result.
        """
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def to_contract(self) -> MemoryReconciliationPreviewRequest:
        """Convert the HTTP request into the application preview contract.

        Returns:
            MemoryReconciliationPreviewRequest: Operation result.
        """
        return MemoryReconciliationPreviewRequest(
            candidate=self.candidate.to_contract(),
            idempotency_key=self.idempotency_key,
            recall_limit=self.recall_limit,
        )


class MemoryReconciliationApplyRequest(StrictSchemaModel):
    """Apply or explicitly retry one reconciliation plan."""

    retry_failed: Annotated[
        bool,
        described_field("Retry failed for this memory reconciliation apply request."),
    ] = False
