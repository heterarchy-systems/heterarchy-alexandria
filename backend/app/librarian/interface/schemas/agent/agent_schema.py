"""Agent profile request and response schemas."""

from __future__ import annotations

from typing import Annotated, Final, cast

from pydantic import (
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.librarian.domain.event_enum.collaboration_enums import LibrarianProfileRole
from app.librarian.domain.types.agent_payload_types import AgentUpdatePayload
from app.shared.schemas.common_schemas import (
    StrictRootSchemaModel,
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.serialization.model_codec import schema_payload
from app.shared.types.extra_types import JSONValue

_NON_NULLABLE_PATCH_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "provider",
    "capabilities",
    "max_librarian_agents",
    "librarian_role",
    "librarian_specialties",
    "librarian_routing_priority",
    "librarian_enabled",
)


class AgentCreateRequest(StrictSchemaModel):
    """Payload for registering an agent profile."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "research-agent",
                    "provider": "OPENAI",
                    "description": "Finds reusable backend implementation guidance.",
                    "capabilities": ["search", "summarize"],
                    "preferred_librarian_provider": "00000000-0000-4000-8000-000000000777",
                    "preferred_librarian_model": "gpt-5.5",
                    "max_librarian_agents": 3,
                    "librarian_role_prompt": "Act as a codebase librarian.",
                    "librarian_role": "SPECIALIST",
                    "librarian_specialties": ["python", "fastapi"],
                    "librarian_routing_priority": 20,
                    "librarian_enabled": True,
                }
            ]
        },
    )

    name: Annotated[str, described_field("Name for this agent create request.")]
    provider: Annotated[str, described_field("Provider for this agent create request.")]
    description: Annotated[
        str | None, described_field("Description for this agent create request.")
    ] = None
    capabilities: Annotated[
        list[str], described_field("Capabilities for this agent create request.")
    ]
    preferred_librarian_provider: Annotated[
        str | None,
        described_field("Preferred librarian provider for this agent create request."),
    ] = None
    preferred_librarian_model: Annotated[
        str | None,
        described_field("Preferred librarian model for this agent create request."),
    ] = None
    max_librarian_agents: Annotated[
        int,
        described_field(
            "Max librarian agents for this agent create request.", ge=1, le=6
        ),
    ] = 1
    librarian_role_prompt: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=4096),
        described_field("Librarian role prompt for this agent create request."),
    ] = None
    librarian_role: Annotated[
        LibrarianProfileRole,
        described_field("Librarian role for this agent create request."),
    ] = LibrarianProfileRole.DEFAULT_SEARCH
    librarian_specialties: Annotated[
        list[str],
        described_field("Librarian specialties for this agent create request."),
    ] = schema_list_default()
    librarian_routing_priority: Annotated[
        int,
        described_field(
            "Librarian routing priority for this agent create request.", ge=0
        ),
    ] = 100
    librarian_enabled: Annotated[
        bool, described_field("Librarian enabled for this agent create request.")
    ] = True


class AgentPatchRequest(StrictSchemaModel):
    """Payload for updating fields on an existing agent."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "research-agent",
                    "description": "Focuses on FastAPI library guidance.",
                    "capabilities": ["search", "recommend"],
                    "preferred_librarian_model": "gpt-5.5",
                    "max_librarian_agents": 2,
                    "librarian_role_prompt": "Find project memory and reusable skills.",
                    "librarian_role": "SPECIALIST",
                    "librarian_specialties": ["fastapi", "oauth"],
                    "librarian_routing_priority": 10,
                    "librarian_enabled": True,
                }
            ]
        }
    )

    name: Annotated[
        str | None, described_field("Name for this agent patch request.")
    ] = None
    provider: Annotated[
        str | None, described_field("Provider for this agent patch request.")
    ] = None
    description: Annotated[
        str | None, described_field("Description for this agent patch request.")
    ] = None
    capabilities: Annotated[
        list[str] | None, described_field("Capabilities for this agent patch request.")
    ] = None
    preferred_librarian_provider: Annotated[
        str | None,
        described_field("Preferred librarian provider for this agent patch request."),
    ] = None
    preferred_librarian_model: Annotated[
        str | None,
        described_field("Preferred librarian model for this agent patch request."),
    ] = None
    max_librarian_agents: Annotated[
        int | None,
        described_field(
            "Max librarian agents for this agent patch request.", ge=1, le=6
        ),
    ] = None
    librarian_role_prompt: Annotated[
        str | None,
        StringConstraints(strict=True, max_length=4096),
        described_field("Librarian role prompt for this agent patch request."),
    ] = None
    librarian_role: Annotated[
        LibrarianProfileRole | None,
        described_field("Librarian role for this agent patch request."),
    ] = None
    librarian_specialties: Annotated[
        list[str] | None,
        described_field("Librarian specialties for this agent patch request."),
    ] = None
    librarian_routing_priority: Annotated[
        int | None,
        described_field(
            "Librarian routing priority for this agent patch request.", ge=0
        ),
    ] = None
    librarian_enabled: Annotated[
        bool | None, described_field("Librarian enabled for this agent patch request.")
    ] = None

    @model_validator(mode="after")
    def require_actionable_patch(self) -> AgentPatchRequest:
        """Reject empty patches and nulls for non-nullable profile fields.

        Returns:
            AgentPatchRequest: Validated patch request.
        """
        patch_values = schema_payload(self, exclude_unset=True)
        if not patch_values:
            raise ValueError("At least one agent field is required")
        for field_name in _NON_NULLABLE_PATCH_FIELDS:
            if field_name in patch_values and patch_values[field_name] is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    def to_payload(self) -> AgentUpdatePayload:
        """Return explicitly supplied patch fields for the application layer.

        Returns:
            AgentUpdatePayload: Patch payload preserving nullable clear requests.
        """
        return cast(AgentUpdatePayload, schema_payload(self, exclude_unset=True))


class AgentResponse(StrictSchemaModel):
    """Agent profile response model."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "00000000-0000-4000-8000-000000000201",
                    "name": "research-agent",
                    "provider": "OPENAI",
                    "description": "Finds reusable backend implementation guidance.",
                    "capabilities": ["search", "summarize"],
                    "preferred_librarian_provider": "00000000-0000-4000-8000-000000000777",
                    "preferred_librarian_model": "gpt-5.5",
                    "max_librarian_agents": 3,
                    "librarian_role_prompt": "Act as a codebase librarian.",
                    "librarian_role": "SPECIALIST",
                    "librarian_specialties": ["python", "fastapi"],
                    "librarian_routing_priority": 20,
                    "librarian_enabled": True,
                    "created_at": "2026-05-12T10:00:00Z",
                    "updated_at": "2026-05-12T10:05:00Z",
                }
            ]
        },
    )

    id: Annotated[str, described_field("Stable identifier for this agent response.")]
    name: Annotated[str, described_field("Name for this agent response.")]
    provider: Annotated[str, described_field("Provider for this agent response.")]
    description: Annotated[
        str | None, described_field("Description for this agent response.")
    ]
    capabilities: Annotated[
        list[str], described_field("Capabilities for this agent response.")
    ]
    preferred_librarian_provider: Annotated[
        str | None,
        described_field("Preferred librarian provider for this agent response."),
    ]
    preferred_librarian_model: Annotated[
        str | None,
        described_field("Preferred librarian model for this agent response."),
    ]
    max_librarian_agents: Annotated[
        int, described_field("Max librarian agents for this agent response.")
    ]
    librarian_role_prompt: Annotated[
        str | None, described_field("Librarian role prompt for this agent response.")
    ]
    librarian_role: Annotated[
        LibrarianProfileRole, described_field("Librarian role for this agent response.")
    ]
    librarian_specialties: Annotated[
        list[str], described_field("Librarian specialties for this agent response.")
    ]
    librarian_routing_priority: Annotated[
        int, described_field("Librarian routing priority for this agent response.")
    ]
    librarian_enabled: Annotated[
        bool, described_field("Librarian enabled for this agent response.")
    ]
    created_at: Annotated[
        AwareTimestamp, described_field("Creation timestamp for this agent response.")
    ]
    updated_at: Annotated[
        AwareTimestamp,
        described_field("Last-update timestamp for this agent response."),
    ]

    @field_validator("librarian_specialties", mode="before")
    @classmethod
    def parse_librarian_specialties(cls, value: JSONValue) -> JSONValue:
        """Normalize legacy null specialties to an empty list.

        Args:
            value: Raw Pydantic boundary value from persisted specialties.

        Returns:
            Raw value for Pydantic list validation, or an empty list for legacy nulls.
        """
        if value is None:
            return []
        return value


class AgentResponseList(StrictRootSchemaModel[list[AgentResponse]]):
    """Root response schema for agent response arrays."""
