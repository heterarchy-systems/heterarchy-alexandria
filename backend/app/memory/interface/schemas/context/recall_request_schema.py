"""Pydantic HTTP and MCP request contracts for high-level memory recall."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.memory.domain.contracts.recall_contracts import (
    RecallExactSelector,
    RecallRequest,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
)
from app.memory.domain.event_enum.recall_enums import RecallScopeMode
from app.obsidian.interface.schemas.obsidian.obsidian_logical_identity_schema import (
    ObsidianLogicalIdentitySchema,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    exclude_none_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import enum_value


class RecallExactSelectorRequest(StrictSchemaModel):
    """Optional source selector evaluated before retrieval-index search."""

    note_id: Annotated[
        str | None,
        Field(
            description="Canonical note identifier for exact recall.", max_length=512
        ),
        exclude_none_field(),
    ] = None
    path: Annotated[
        str | None,
        Field(
            description="Canonical vault-relative path for exact recall.",
            max_length=2048,
        ),
        exclude_none_field(),
    ] = None
    logical_identity: Annotated[
        ObsidianLogicalIdentitySchema | None,
        Field(description="Logical report identity for exact recall."),
        exclude_none_field(),
    ] = None

    @field_validator("note_id", "path")
    @classmethod
    def normalize_selector_text(cls, value: str | None) -> str | None:
        """Normalize optional exact selector text."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_selector(self) -> RecallExactSelectorRequest:
        """Require one concrete exact selector."""
        selected = sum(
            (
                self.note_id is not None,
                self.path is not None,
                self.logical_identity is not None,
            )
        )
        if selected != 1:
            raise ValueError(
                "exact_selector requires exactly one of note_id, path, or logical_identity"
            )
        return self

    def to_contract(self) -> RecallExactSelector:
        """Convert the boundary selector into its typed domain contract."""
        return RecallExactSelector(
            note_id=self.note_id,
            path=self.path,
            logical_identity=(
                None
                if self.logical_identity is None
                else self.logical_identity.to_identity()
            ),
        )


class RecallRequestSchema(StrictSchemaModel):
    """High-level recall request with AUTO and STRICT scope modes."""

    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=10000),
        Field(description="Natural-language query for high-level recall."),
    ]
    limit: Annotated[
        int,
        Field(description="Maximum recalled contexts.", ge=1, le=50),
    ] = 5
    scope_mode: Annotated[
        RecallScopeMode,
        Field(description="Scope identity resolution mode for high-level recall."),
    ] = RecallScopeMode.AUTO
    include_scopes: Annotated[
        list[ContextScope],
        Field(description="Optional explicit scope lanes for STRICT recall."),
    ] = schema_list_default()
    project: Annotated[
        str | None,
        Field(description="Primary project identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    workspace_id: Annotated[
        str | None,
        Field(description="Workspace identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    agent_id: Annotated[
        str | None,
        Field(description="Agent identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    session_id: Annotated[
        str | None,
        Field(description="Session identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description="User identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    related_projects: Annotated[
        list[str],
        Field(description="Bounded related project expansion inputs.", max_length=4),
    ] = schema_list_default()
    exact_selector: Annotated[
        RecallExactSelectorRequest | None,
        Field(description="Optional exact canonical selector."),
        exclude_none_field(),
    ] = None
    as_of: Annotated[
        AwareTimestamp | None,
        Field(description="Historical instant for temporal recall."),
        exclude_none_field(),
    ] = None
    kind: Annotated[
        ContextKind | None,
        Field(description="Optional Context kind filter."),
        exclude_none_field(),
    ] = None
    include_lifecycle_statuses: Annotated[
        list[ContextRecallLifecycleStatus],
        Field(description="Optional lifecycle eligibility filter."),
    ] = schema_list_default()

    @field_validator(
        "include_scopes",
        "include_lifecycle_statuses",
        mode="before",
    )
    @classmethod
    def normalize_optional_lists(cls, value: JSONValue) -> JSONValue:
        """Normalize omitted/null optional enum lists to empty lists."""
        return [] if value is None else value

    @field_validator(
        "query", "project", "workspace_id", "agent_id", "session_id", "user_id"
    )
    @classmethod
    def normalize_identity_text(cls, value: str | None) -> str | None:
        """Normalize request query and optional identity text."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("related_projects")
    @classmethod
    def normalize_related_projects(cls, value: list[str]) -> list[str]:
        """Normalize and bound related-project expansion inputs."""
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) > 4:
            raise ValueError("related_projects must contain at most 4 projects")
        return normalized

    def to_contract(self) -> RecallRequest:
        """Convert the external schema into the internal typed request."""
        return RecallRequest(
            query=self.query,
            limit=self.limit,
            scope_mode=enum_value(self.scope_mode, RecallScopeMode, "scope_mode"),
            include_scopes=tuple(
                enum_value(item, ContextScope, "include_scopes")
                for item in self.include_scopes
            ),
            project=self.project,
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
            user_id=self.user_id,
            related_projects=tuple(self.related_projects),
            selector=(
                None
                if self.exact_selector is None
                else self.exact_selector.to_contract()
            ),
            as_of=self.as_of,
            kind=(
                None
                if self.kind is None
                else enum_value(self.kind, ContextKind, "kind")
            ),
            include_lifecycle_statuses=tuple(
                enum_value(
                    item,
                    ContextRecallLifecycleStatus,
                    "include_lifecycle_statuses",
                )
                for item in self.include_lifecycle_statuses
            ),
        )
