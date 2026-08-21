"""Pydantic I/O schemas for librarian OAuth lifecycle routes."""

from __future__ import annotations

from typing import Annotated, Literal

from app.connections.domain.event_enum.provider_enums import (
    OAuthConnectionStatus,
    OAuthPollStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp
from pydantic import ConfigDict


class LibrarianOAuthStartResponse(StrictSchemaModel):
    """Response returned after starting a device OAuth flow."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider_id": "00000000-0000-4000-8000-000000000456",
                    "status": "pending",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://login.example/device",
                    "verification_uri_complete": (
                        "https://login.example/device?user_code=ABCD-1234"
                    ),
                    "expires_at": "2026-05-15T12:10:00Z",
                    "interval_seconds": 5,
                }
            ]
        }
    )

    provider_id: Annotated[
        str,
        described_field(
            "Provider identifier for this librarian o auth start response."
        ),
    ]
    status: Annotated[
        OAuthPollStatus,
        described_field("Status for this librarian o auth start response."),
    ]
    user_code: Annotated[
        str, described_field("User code for this librarian o auth start response.")
    ]
    verification_uri: Annotated[
        str,
        described_field("Verification URI for this librarian o auth start response."),
    ]
    verification_uri_complete: Annotated[
        str | None,
        described_field(
            "Verification URI complete for this librarian o auth start response."
        ),
    ]
    expires_at: Annotated[
        AwareTimestamp,
        described_field("Expires at for this librarian o auth start response."),
    ]
    interval_seconds: Annotated[
        int,
        described_field("Interval seconds for this librarian o auth start response."),
    ]


class LibrarianOAuthStatusResponse(StrictSchemaModel):
    """OAuth connection status response without credential material."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider_id": "00000000-0000-4000-8000-000000000456",
                    "status": "connected",
                    "connected": True,
                    "expires_at": "2026-05-15T13:00:00Z",
                    "refresh_required": False,
                    "message": None,
                }
            ]
        }
    )

    provider_id: Annotated[
        str,
        described_field(
            "Provider identifier for this librarian o auth status response."
        ),
    ]
    status: Annotated[
        OAuthConnectionStatus,
        described_field("Status for this librarian o auth status response."),
    ]
    connected: Annotated[
        bool, described_field("Connected for this librarian o auth status response.")
    ]
    expires_at: Annotated[
        AwareTimestamp | None,
        described_field("Expires at for this librarian o auth status response."),
    ]
    refresh_required: Annotated[
        bool,
        described_field("Refresh required for this librarian o auth status response."),
    ]
    reconnect_required: Annotated[
        bool,
        described_field(
            "Reconnect required for this librarian o auth status response."
        ),
    ]
    next_action: Annotated[
        Literal["none", "poll", "refresh", "start_oauth"],
        described_field("Next action for this librarian o auth status response."),
    ]
    message: Annotated[
        str | None,
        described_field("Message for this librarian o auth status response."),
    ]
