from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.shared.schemas.common_schemas import StrictSchemaModel


class ContextDeltaRequest(StrictSchemaModel):
    """Payload for one bounded Context change-log delta read."""

    cursor_token: Annotated[
        str | None,
        Field(
            description="Opaque cursor token from a previous delta page; omit for a fresh read."
        ),
    ] = None
    max_rows: Annotated[
        int,
        Field(description="Maximum change entries for this delta page.", ge=1, le=64),
    ] = 32


class ContextChangeEntryResponse(StrictSchemaModel):
    """One recorded Context mutation identity record."""

    sequence: Annotated[
        int, Field(description="Global change-log sequence for this entry.")
    ]
    context_id: Annotated[str, Field(description="Identifier of the mutated Context.")]
    change_kind: Annotated[
        str, Field(description="Recorded mutation kind for this entry.")
    ]
    content_hash: Annotated[
        str, Field(description="Hex-encoded post-change content digest.")
    ]
    recorded_at: Annotated[
        str, Field(description="UTC timestamp shared with the mutated Context row.")
    ]


class ContextDeltaResponse(StrictSchemaModel):
    """One bounded Context change-log delta page."""

    entries: Annotated[
        list[ContextChangeEntryResponse],
        Field(description="Change entries in sequence order."),
    ]
    next_cursor: Annotated[
        str,
        Field(description="Opaque cursor token for the next delta page."),
    ]
    has_more: Annotated[
        bool, Field(description="Whether further entries exist after this page.")
    ]
