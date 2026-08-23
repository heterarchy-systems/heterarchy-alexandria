"""Connection provider read models returned by repository ports."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from app.connections.domain.event_enum.provider_enums import AuthType, ProviderType
from app.shared.types.extra_types import JSONObject


@dataclass(slots=True)
class LibrarianProvider:
    """Read model for external provider/connection configuration."""

    id: str
    name: str
    provider_type: ProviderType | str
    auth_type: AuthType | str
    enabled: bool
    config: JSONObject
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Normalize supported persisted enum values at the read-model boundary."""
        with suppress(ValueError):
            self.provider_type = ProviderType(self.provider_type)
        with suppress(ValueError):
            self.auth_type = AuthType(self.auth_type)
