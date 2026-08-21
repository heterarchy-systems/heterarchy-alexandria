"""HTTP schemas for Obsidian vault inventory operations."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianVaultInventoryRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianVaultInventoryItem,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class ObsidianVaultInventoryRequestSchema(StrictSchemaModel):
    """Request to inventory managed Obsidian notes under one scope."""

    scope_path: Annotated[
        str | None,
        described_field("Scope path for this Obsidian vault inventory request."),
    ] = None

    def to_command(self) -> ObsidianVaultInventoryRequest:
        """Convert request into application command.

        Returns:
            Application inventory request.
        """
        return ObsidianVaultInventoryRequest(scope_path=self.scope_path)


class ObsidianVaultInventoryItemResponse(StrictSchemaModel):
    """One managed note inventory item."""

    id: Annotated[
        str,
        described_field(
            "Stable identifier for this Obsidian vault inventory item response."
        ),
    ]
    path: Annotated[
        str, described_field("Path for this Obsidian vault inventory item response.")
    ]
    alexandria_type: Annotated[
        AlexandriaNoteType,
        described_field(
            "Alexandria type for this Obsidian vault inventory item response."
        ),
    ]
    title: Annotated[
        str, described_field("Title for this Obsidian vault inventory item response.")
    ]
    status: Annotated[
        str, described_field("Status for this Obsidian vault inventory item response.")
    ]
    tags: Annotated[
        list[str],
        described_field("Tags for this Obsidian vault inventory item response."),
    ]
    project: Annotated[
        str | None,
        described_field("Project for this Obsidian vault inventory item response."),
    ]
    size_bytes: Annotated[
        int,
        described_field("Size bytes for this Obsidian vault inventory item response."),
    ]
    modified_at: Annotated[
        AwareTimestamp,
        described_field("Modified at for this Obsidian vault inventory item response."),
    ]

    @classmethod
    def from_entity(
        cls,
        item: ObsidianVaultInventoryItem,
    ) -> ObsidianVaultInventoryItemResponse:
        """Create response from inventory item.

        Args:
            item: Inventory item entity.

        Returns:
            HTTP inventory item.
        """
        return cls(
            id=item.note_id,
            path=item.relative_path,
            alexandria_type=item.alexandria_type,
            title=item.title,
            status=item.status,
            tags=list(item.tags),
            project=item.project,
            size_bytes=item.size_bytes,
            modified_at=item.modified_at,
        )


class ObsidianVaultInventoryResponse(StrictSchemaModel):
    """Inventory response."""

    items: Annotated[
        list[ObsidianVaultInventoryItemResponse],
        described_field("Items for this Obsidian vault inventory response."),
    ]
    total: Annotated[
        int, described_field("Total for this Obsidian vault inventory response.")
    ]
