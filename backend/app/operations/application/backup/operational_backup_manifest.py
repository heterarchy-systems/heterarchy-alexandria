"""Versioned manifest contract for portable operational backups."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class OperationalBackupArtifact(StrictSchemaModel):
    """One hash-verified file stored under a backup directory."""

    kind: Annotated[
        Literal["canonical_vault", "operational_database", "librarian_checkpoint"],
        described_field("Kind for this operational backup artifact."),
    ]
    relative_path: Annotated[
        str, described_field("Relative path for this operational backup artifact.")
    ]
    sha256: Annotated[
        str, described_field("SHA-256 for this operational backup artifact.")
    ]
    size_bytes: Annotated[
        int, described_field("Size bytes for this operational backup artifact.")
    ]
    plaintext_sha256: Annotated[
        str,
        described_field("Plaintext SHA-256 for this operational backup artifact."),
    ]


class OperationalBackupManifest(StrictSchemaModel):
    """Self-contained evidence needed to verify and restore one backup."""

    schema_version: Annotated[
        Literal[2],
        described_field("Schema version for this operational backup manifest."),
    ] = 2
    encryption: Annotated[
        Literal["fernet"],
        described_field("Encryption for this operational backup manifest."),
    ] = "fernet"
    backup_id: Annotated[
        str, described_field("Backup identifier for this operational backup manifest.")
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this operational backup manifest."),
    ]
    vault_source_path: Annotated[
        str,
        described_field("Vault source path for this operational backup manifest."),
    ]
    alexandria_root: Annotated[
        str,
        described_field("Alexandria root for this operational backup manifest."),
    ]
    operational_database_source_path: Annotated[
        str,
        described_field(
            "Operational database source path for this operational backup manifest."
        ),
    ]
    librarian_checkpoint_source_path: Annotated[
        str | None,
        described_field(
            "Librarian checkpoint source path for this operational backup manifest."
        ),
    ]
    artifacts: Annotated[
        list[OperationalBackupArtifact],
        described_field("Artifacts for this operational backup manifest."),
    ]

    @property
    def total_bytes(self) -> int:
        """Return the total content bytes represented by the manifest.

        Returns:
            Sum of all artifact sizes.
        """
        return sum(item.size_bytes for item in self.artifacts)

    @property
    def created_datetime(self) -> datetime:
        """Expose the validated aware timestamp as a datetime.

        Returns:
            Aware backup creation time.
        """
        return self.created_at
