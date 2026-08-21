"""HTTP schemas for Obsidian runtime settings."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianVaultSettingsUpdate
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from pydantic import StringConstraints


class ObsidianVaultSettingsUpdateRequest(StrictSchemaModel):
    """Request to change the backend Obsidian vault destination."""

    vault_path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Vault path for this Obsidian vault settings update request."),
    ]
    alexandria_root: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field(
            "Alexandria root for this Obsidian vault settings update request."
        ),
    ] = "."
    initialize: Annotated[
        bool,
        described_field("Initialize for this Obsidian vault settings update request."),
    ] = True
    reindex: Annotated[
        bool,
        described_field("Reindex for this Obsidian vault settings update request."),
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
