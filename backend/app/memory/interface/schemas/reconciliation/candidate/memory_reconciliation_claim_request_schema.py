"""Canonical claim and source-reference request schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator

from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    CanonicalClaimQualifier,
    MemorySourceReference,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import MemoryClaimPolarity
from app.memory.interface.schemas.reconciliation.reconciliation_string_types import (
    ReconciliationTitleText,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.types_convert_utils import enum_value


class CanonicalClaimQualifierRequest(StrictSchemaModel):
    """One named canonical claim qualifier."""

    name: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=255),
        described_field("Name for this canonical claim qualifier request."),
    ]
    value: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=2000),
        described_field("Value for this canonical claim qualifier request."),
    ]

    @field_validator("name", "value")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """Normalize required qualifier text.

        Args:
            value: Value.

        Returns:
            str: Operation result.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("qualifier text is required")
        return normalized

    def to_entity(self) -> CanonicalClaimQualifier:
        """Convert the HTTP boundary value into an internal qualifier.

        Returns:
            CanonicalClaimQualifier: Operation result.
        """
        return CanonicalClaimQualifier(name=self.name, value=self.value)


class CanonicalClaimRequest(StrictSchemaModel):
    """Canonical proposition supplied for deterministic reconciliation."""

    subject: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=1000),
        described_field("Subject for this canonical claim request."),
    ]
    predicate: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=500),
        described_field("Predicate for this canonical claim request."),
    ]
    object: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=4000),
        described_field("Object for this canonical claim request."),
    ]
    qualifiers: Annotated[
        list[CanonicalClaimQualifierRequest],
        described_field("Qualifiers for this canonical claim request."),
    ] = schema_list_default()
    valid_from: Annotated[
        AwareTimestamp | None,
        described_field("Valid from for this canonical claim request."),
    ] = None
    valid_to: Annotated[
        AwareTimestamp | None,
        described_field("Valid to for this canonical claim request."),
    ] = None
    polarity: Annotated[
        MemoryClaimPolarity,
        described_field("Polarity for this canonical claim request."),
    ] = MemoryClaimPolarity.POSITIVE

    @field_validator("subject", "predicate", "object")
    @classmethod
    def normalize_claim_text(cls, value: str) -> str:
        """Normalize required claim text.

        Args:
            value: Value.

        Returns:
            str: Operation result.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("canonical claim text is required")
        return normalized

    def to_entity(
        self,
        scope: ContextScope,
        project: str | None,
    ) -> CanonicalClaim:
        """Convert the request into an internal canonical claim.

        Args:
            scope: Scope.
            project: Project.

        Returns:
            CanonicalClaim: Operation result.
        """
        return CanonicalClaim(
            subject=self.subject,
            predicate=self.predicate,
            object=self.object,
            qualifiers=tuple(item.to_entity() for item in self.qualifiers),
            scope=scope,
            project=project,
            valid_from=self.valid_from,
            valid_to=self.valid_to,
            polarity=enum_value(
                self.polarity,
                MemoryClaimPolarity,
                "polarity",
            ),
        )


class MemorySourceReferenceRequest(StrictSchemaModel):
    """One explicit evidence or provenance reference."""

    source_type: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=255),
        described_field("Source type for this memory source reference request."),
    ]
    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=1000),
        described_field("Source identifier for this memory source reference request."),
    ]
    title: Annotated[
        ReconciliationTitleText,
        described_field("Title for this memory source reference request."),
    ]
    detail_path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=4000),
        described_field("Detail path for this memory source reference request."),
    ]
    source_hash: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=512),
        described_field("Source hash for this memory source reference request."),
    ] = None
    observed_at: Annotated[
        AwareTimestamp | None,
        described_field("Observed at for this memory source reference request."),
    ] = None

    @field_validator("source_type", "source_id", "title", "detail_path")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """Normalize required source reference text.

        Args:
            value: Value.

        Returns:
            str: Operation result.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("source reference text is required")
        return normalized

    def to_entity(self) -> MemorySourceReference:
        """Convert the request into an internal source reference.

        Returns:
            MemorySourceReference: Operation result.
        """
        return MemorySourceReference(
            source_type=self.source_type,
            source_id=self.source_id,
            title=self.title,
            detail_path=self.detail_path,
            source_hash=self.source_hash,
            observed_at=self.observed_at,
        )
