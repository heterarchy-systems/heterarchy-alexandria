"""HTTP schemas for Obsidian runtime settings."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianVaultSettingsUpdate
from app.obsidian.interface.schemas.obsidian.obsidian_string_types import (
    ObsidianPathText,
)
from app.shared.schemas.common_schemas import StrictSchemaModel


class ObsidianVaultSettingsUpdateRequest(StrictSchemaModel):
    """Request to change the backend Obsidian vault destination."""

    vault_path: Annotated[
        ObsidianPathText,
        Field(
            description="Vault path for this Obsidian vault settings update request."
        ),
    ]
    alexandria_root: Annotated[
        ObsidianPathText,
        Field(
            description="Alexandria root for this Obsidian vault settings update request."
        ),
    ] = "."
    initialize: Annotated[
        bool,
        Field(
            description="Initialize for this Obsidian vault settings update request."
        ),
    ] = True
    reindex: Annotated[
        bool,
        Field(description="Reindex for this Obsidian vault settings update request."),
    ] = True

    def to_command(self) -> ObsidianVaultSettingsUpdate:
        """Convert request into an application update command.

        Returns:
            Application vault settings update command.
        """
        return ObsidianVaultSettingsUpdate(
            vault_path=self.vault_path,
            alexandria_root=self.alexandria_root,
            initialize=self.initialize,
            reindex=self.reindex,
        )
