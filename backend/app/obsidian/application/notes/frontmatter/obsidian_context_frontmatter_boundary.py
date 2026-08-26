"""Pydantic validation boundary for Context-specific Obsidian frontmatter."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BeforeValidator,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.memory.domain.event_enum.context_enums import (
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    MemoryFunction,
)
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_values import (
    frontmatter_validation_message,
    normalized_content_hash,
    normalized_context_version,
    normalized_legacy_timestamp,
    normalized_scope_text,
    normalized_status_text,
    normalized_uppercase_text,
    reference_tuple,
    string_or_none,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianContextLifecycleStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.type_validation.strict_json_value import model_validate_json_value
from app.shared.types.extra_types import JSONObject, JSONValue


class ContextProvenanceBoundary(StrictSchemaModel):
    """Boundary schema for the optional nested provenance input shape."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=False,
        validate_default=True,
    )

    source_actor_id: Annotated[
        str | None,
        described_field(
            "Source actor identifier for this context provenance boundary."
        ),
    ] = None
    source_actor_type: Annotated[
        ContextSourceType | None,
        described_field("Source actor type for this context provenance boundary."),
    ] = None
    source_run_id: Annotated[
        str | None,
        described_field("Source run identifier for this context provenance boundary."),
    ] = None
    external_run_id: Annotated[
        str | None,
        described_field(
            "External run identifier for this context provenance boundary."
        ),
    ] = None
    artifact_refs: Annotated[
        tuple[str, ...],
        described_field("Artifact refs for this context provenance boundary."),
    ] = ()
    evidence_refs: Annotated[
        tuple[str, ...],
        described_field("Evidence refs for this context provenance boundary."),
    ] = ()
    confidence: Annotated[
        ContextImportance | None,
        described_field("Confidence for this context provenance boundary."),
    ] = None

    @field_validator("source_actor_type", "confidence", mode="before")
    @classmethod
    def normalize_uppercase_enum(cls, value: JSONValue) -> str | None:
        """Normalize nested provenance enum values.

        Args:
            value: Raw provenance enum value.

        Returns:
            Canonical uppercase text when present.
        """
        return normalized_uppercase_text(value)

    @field_validator(
        "source_actor_id",
        "source_run_id",
        "external_run_id",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: JSONValue) -> str | None:
        """Normalize optional nested provenance text.

        Args:
            value: Raw provenance scalar value.

        Returns:
            Trimmed text when present.
        """
        return string_or_none(value)

    @field_validator(
        "artifact_refs",
        "evidence_refs",
        mode="before",
    )
    @classmethod
    def normalize_reference_list(cls, value: JSONValue) -> tuple[str, ...]:
        """Normalize nested provenance reference lists.

        Args:
            value: Raw reference collection.

        Returns:
            Immutable normalized references.
        """
        return reference_tuple(value)


class ContextFrontmatterBoundary(StrictSchemaModel):
    """Boundary schema for known Context frontmatter identity fields."""

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        use_enum_values=False,
        validate_default=True,
    )

    scope: Annotated[
        ContextScope | None,
        described_field("Scope for this context frontmatter boundary."),
    ] = None
    project: Annotated[
        str | None, described_field("Project for this context frontmatter boundary.")
    ] = None
    workspace_id: Annotated[
        str | None,
        described_field("Workspace identifier for this context frontmatter boundary."),
    ] = None
    agent_id: Annotated[
        str | None,
        described_field("Agent identifier for this context frontmatter boundary."),
    ] = None
    user_id: Annotated[
        str | None,
        described_field("User identifier for this context frontmatter boundary."),
    ] = None
    session_id: Annotated[
        str | None,
        described_field("Session identifier for this context frontmatter boundary."),
    ] = None
    visibility: Annotated[
        ContextScope | None,
        described_field("Visibility for this context frontmatter boundary."),
    ] = None
    status: Annotated[
        ObsidianContextLifecycleStatus | None,
        described_field("Status for this context frontmatter boundary."),
    ] = None
    source_actor_id: Annotated[
        str | None,
        described_field(
            "Source actor identifier for this context frontmatter boundary."
        ),
    ] = None
    source_actor_type: Annotated[
        ContextSourceType | None,
        described_field("Source actor type for this context frontmatter boundary."),
    ] = None
    source_run_id: Annotated[
        str | None,
        described_field("Source run identifier for this context frontmatter boundary."),
    ] = None
    external_run_id: Annotated[
        str | None,
        described_field(
            "External run identifier for this context frontmatter boundary."
        ),
    ] = None
    artifact_refs: Annotated[
        tuple[str, ...],
        described_field("Artifact refs for this context frontmatter boundary."),
    ] = ()
    evidence_refs: Annotated[
        tuple[str, ...],
        described_field("Evidence refs for this context frontmatter boundary."),
    ] = ()
    confidence: Annotated[
        ContextImportance | None,
        described_field("Confidence for this context frontmatter boundary."),
    ] = None
    provenance: Annotated[
        ContextProvenanceBoundary | None,
        described_field("Provenance for this context frontmatter boundary."),
    ] = None
    content_hash: Annotated[
        str | None,
        described_field("Content hash for this context frontmatter boundary."),
    ] = None
    version: Annotated[
        int | None,
        BeforeValidator(normalized_context_version),
        described_field("Version for this context frontmatter boundary."),
    ] = None
    supersedes_context_id: Annotated[
        str | None,
        described_field(
            "Supersedes context identifier for this context frontmatter boundary."
        ),
    ] = None
    superseded_by_context_id: Annotated[
        str | None,
        described_field(
            "Superseded by context identifier for this context frontmatter boundary."
        ),
    ] = None
    context_kind: Annotated[
        ContextKind | None,
        described_field("Context kind for this context frontmatter boundary."),
    ] = None
    memory_function: Annotated[
        MemoryFunction | None,
        described_field("Memory function for this context frontmatter boundary."),
    ] = None
    kind: Annotated[
        str | None, described_field("Kind for this context frontmatter boundary.")
    ] = None
    created_at: Annotated[
        AwareTimestamp | None,
        described_field("Creation timestamp for this context frontmatter boundary."),
    ] = None
    updated_at: Annotated[
        AwareTimestamp | None,
        described_field("Last-update timestamp for this context frontmatter boundary."),
    ] = None
    recorded_at: Annotated[
        AwareTimestamp | None,
        described_field("Recorded at for this context frontmatter boundary."),
    ] = None
    observed_at: Annotated[
        AwareTimestamp | None,
        described_field("Observed at for this context frontmatter boundary."),
    ] = None
    valid_from: Annotated[
        AwareTimestamp | None,
        described_field("Valid from for this context frontmatter boundary."),
    ] = None
    valid_to: Annotated[
        AwareTimestamp | None,
        described_field("Valid to for this context frontmatter boundary."),
    ] = None
    reconciliation_candidate_id: Annotated[
        str | None,
        described_field(
            "Reconciliation candidate identifier for this context frontmatter boundary."
        ),
    ] = None
    conflict_set_ids: Annotated[
        tuple[str, ...],
        described_field(
            "Conflict set identifiers for this context frontmatter boundary."
        ),
    ] = ()

    @field_validator("scope", "visibility", "status", mode="before")
    @classmethod
    def normalize_scope_or_status(
        cls,
        value: JSONValue,
        info: ValidationInfo,
    ) -> str | None:
        """Normalize scope and lifecycle enum spellings.

        Args:
            value: Raw frontmatter enum value.
            info: Pydantic field validation metadata.

        Returns:
            Canonical enum text when present.
        """
        if info.field_name == "status":
            return normalized_status_text(value)
        return normalized_scope_text(value)

    @field_validator(
        "source_actor_type",
        "confidence",
        "context_kind",
        "memory_function",
        "kind",
        mode="before",
    )
    @classmethod
    def normalize_uppercase_enum(cls, value: JSONValue) -> str | None:
        """Normalize enum-like and legacy kind text to uppercase spelling.

        Args:
            value: Raw enum-like value.

        Returns:
            Canonical uppercase text when present.
        """
        return normalized_uppercase_text(value)

    @field_validator(
        "project",
        "workspace_id",
        "agent_id",
        "user_id",
        "session_id",
        "source_actor_id",
        "source_run_id",
        "external_run_id",
        "supersedes_context_id",
        "superseded_by_context_id",
        "reconciliation_candidate_id",
        "content_hash",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(
        cls,
        value: JSONValue,
        info: ValidationInfo,
    ) -> str | None:
        """Normalize optional text and validate content hashes.

        Args:
            value: Raw frontmatter scalar value.
            info: Pydantic field validation metadata.

        Returns:
            Canonical optional text when present.
        """
        if info.field_name == "content_hash":
            return normalized_content_hash(value)
        return string_or_none(value)

    @field_validator(
        "artifact_refs",
        "evidence_refs",
        "conflict_set_ids",
        mode="before",
    )
    @classmethod
    def normalize_reference_list(cls, value: JSONValue) -> tuple[str, ...]:
        """Normalize provenance reference lists without accepting mappings.

        Args:
            value: Raw provenance reference collection.

        Returns:
            Immutable normalized reference values.
        """
        return reference_tuple(value)

    @field_validator(
        "created_at",
        "updated_at",
        "recorded_at",
        "observed_at",
        "valid_from",
        "valid_to",
        mode="before",
    )
    @classmethod
    def normalize_timestamp(cls, value: JSONValue) -> JSONValue:
        """Expand legacy date-only timestamps to an aware UTC instant.

        Args:
            value: Raw timestamp value.

        Returns:
            Aware timestamp text for date-only input, otherwise the input.
        """
        return normalized_legacy_timestamp(value)

    @model_validator(mode="after")
    def reject_conflicting_provenance_shapes(self) -> ContextFrontmatterBoundary:
        """Reject ambiguous flat and nested provenance values.

        Returns:
            Validated boundary model when the representations agree.
        """
        nested = self.provenance
        if nested is None:
            return self
        provenance_pairs = (
            ("source_actor_id", self.source_actor_id, nested.source_actor_id),
            ("source_actor_type", self.source_actor_type, nested.source_actor_type),
            ("source_run_id", self.source_run_id, nested.source_run_id),
            ("external_run_id", self.external_run_id, nested.external_run_id),
            ("artifact_refs", self.artifact_refs, nested.artifact_refs),
            ("evidence_refs", self.evidence_refs, nested.evidence_refs),
            ("confidence", self.confidence, nested.confidence),
        )
        for field_name, flat_value, nested_value in provenance_pairs:
            if flat_value not in (None, ()) and flat_value != nested_value:
                raise ValueError(
                    f"conflicting flat and nested provenance field: {field_name}"
                )
        return self


def validate_context_frontmatter(frontmatter: JSONObject) -> ContextFrontmatterBoundary:
    """Validate raw Context frontmatter and translate boundary failures.

    Args:
        frontmatter: Parsed JSON-compatible frontmatter payload.

    Returns:
        Validated Context frontmatter boundary model.

    Raises:
        ValueError: If a known Context field is invalid.
    """
    try:
        return model_validate_json_value(ContextFrontmatterBoundary, frontmatter)
    except ValidationError as exc:
        raise ValueError(frontmatter_validation_message(exc)) from exc
