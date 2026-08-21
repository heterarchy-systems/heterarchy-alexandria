"""Librarian provider schemas."""

from __future__ import annotations

from typing import Annotated, cast

from app.connections.domain.event_enum.provider_enums import AuthType, ProviderType
from app.connections.domain.types.librarian_provider_payload_types import (
    LibrarianProviderPatchPayload,
)
from app.shared.schemas.common_schemas import (
    StrictRootSchemaModel,
    StrictSchemaModel,
    described_field,
    schema_dict_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.serialization.model_codec import schema_payload
from app.shared.types.extra_types import JSONObject
from pydantic import ConfigDict


class LibrarianProviderCreateRequest(StrictSchemaModel):
    """Payload for creating a provider configuration."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "default-openai",
                    "provider_type": "OPENAI",
                    "auth_type": "API_KEY",
                    "enabled": True,
                    "config": {"model": "gpt-5.5"},
                    "api_key": "sk-local-redacted",
                    "oauth_access_token": None,
                }
            ]
        }
    )

    name: Annotated[
        str, described_field("Name for this librarian provider create request.")
    ]
    provider_type: Annotated[
        ProviderType,
        described_field("Provider type for this librarian provider create request."),
    ]
    auth_type: Annotated[
        AuthType,
        described_field("Auth type for this librarian provider create request."),
    ]
    enabled: Annotated[
        bool,
        described_field("Whether this librarian provider create request is enabled."),
    ] = True
    config: Annotated[
        JSONObject,
        described_field("Config for this librarian provider create request."),
    ] = schema_dict_default()
    api_key: Annotated[
        str | None,
        described_field(
            "API key for this librarian provider create request.",
            repr=False,
            json_schema_extra={"writeOnly": True},
        ),
    ] = None
    oauth_access_token: Annotated[
        str | None,
        described_field(
            "OAuth access token for this librarian provider create request.",
            repr=False,
            json_schema_extra={"writeOnly": True},
        ),
    ] = None


class LibrarianProviderPatchRequest(StrictSchemaModel):
    """Payload for updating provider configuration."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "enabled": False,
                    "config": {"model": "gpt-5.5", "timeout_seconds": 30},
                }
            ]
        }
    )

    name: Annotated[
        str | None, described_field("Name for this librarian provider patch request.")
    ] = None
    provider_type: Annotated[
        ProviderType | None,
        described_field("Provider type for this librarian provider patch request."),
    ] = None
    auth_type: Annotated[
        AuthType | None,
        described_field("Auth type for this librarian provider patch request."),
    ] = None
    enabled: Annotated[
        bool | None,
        described_field("Whether this librarian provider patch request is enabled."),
    ] = None
    config: Annotated[
        JSONObject | None,
        described_field("Config for this librarian provider patch request."),
    ] = None
    api_key: Annotated[
        str | None,
        described_field(
            "API key for this librarian provider patch request.",
            repr=False,
            json_schema_extra={"writeOnly": True},
        ),
    ] = None
    oauth_access_token: Annotated[
        str | None,
        described_field(
            "OAuth access token for this librarian provider patch request.",
            repr=False,
            json_schema_extra={"writeOnly": True},
        ),
    ] = None

    def to_payload(self) -> LibrarianProviderPatchPayload:
        """Return a typed service-layer patch payload.

        Returns:
            LibrarianProviderPatchPayload: Provider patch fields excluding absent values.
        """
        return cast(
            LibrarianProviderPatchPayload,
            schema_payload(self, exclude_none=True, exclude_unset=True),
        )


class LibrarianProviderResponse(StrictSchemaModel):
    """Provider response model with timestamps."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "00000000-0000-4000-8000-000000000456",
                    "name": "default-openai",
                    "provider_type": "OPENAI",
                    "auth_type": "API_KEY",
                    "enabled": True,
                    "config": {"model": "gpt-5.5"},
                    "created_at": "2026-05-12T10:00:00Z",
                    "updated_at": "2026-05-12T10:05:00Z",
                }
            ]
        }
    )

    id: Annotated[
        str, described_field("Stable identifier for this librarian provider response.")
    ]
    name: Annotated[str, described_field("Name for this librarian provider response.")]
    provider_type: Annotated[
        ProviderType,
        described_field("Provider type for this librarian provider response."),
    ]
    auth_type: Annotated[
        AuthType, described_field("Auth type for this librarian provider response.")
    ]
    enabled: Annotated[
        bool, described_field("Whether this librarian provider response is enabled.")
    ]
    config: Annotated[
        JSONObject, described_field("Config for this librarian provider response.")
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this librarian provider response."),
    ]
    updated_at: Annotated[
        AwareTimestamp,
        described_field("Last-update timestamp for this librarian provider response."),
    ]


class LibrarianProviderResponseList(
    StrictRootSchemaModel[list[LibrarianProviderResponse]]
):
    """Root response schema for librarian provider response arrays."""


class LibrarianProviderTestRequest(StrictSchemaModel):
    """Payload for connection test."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"test_query": "Suggest a FastAPI testing skill."}]
        }
    )

    test_query: Annotated[
        str, described_field("Test query for this librarian provider test request.")
    ] = "ping"


class LibrarianProviderTestResponse(StrictSchemaModel):
    """Provider test response."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider_id": "00000000-0000-4000-8000-000000000456",
                    "ok": True,
                    "message": "Provider responded successfully.",
                }
            ]
        }
    )

    provider_id: Annotated[
        str,
        described_field(
            "Provider identifier for this librarian provider test response."
        ),
    ]
    ok: Annotated[
        bool,
        described_field(
            "Whether this librarian provider test response operation succeeded."
        ),
    ]
    message: Annotated[
        str, described_field("Message for this librarian provider test response.")
    ]
