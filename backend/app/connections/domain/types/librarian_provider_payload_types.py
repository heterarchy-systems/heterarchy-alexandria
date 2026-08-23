"""Domain-owned librarian provider payload type contracts."""

from __future__ import annotations

from datetime import datetime

from typing_extensions import TypedDict

from app.connections.domain.event_enum.provider_enums import AuthType, ProviderType
from app.shared.types.extra_types import JSONObject


class LibrarianProviderPayload(TypedDict, closed=True):
    """Shaped public payload for a librarian provider read model."""

    id: str
    name: str
    provider_type: ProviderType
    auth_type: AuthType
    enabled: bool
    config: JSONObject
    created_at: datetime
    updated_at: datetime


class LibrarianProviderCreateRecord(TypedDict, closed=True):
    """Persistence record for creating a librarian provider row."""

    name: str
    provider_type: str
    auth_type: str
    enabled: bool
    config: JSONObject
    created_at: datetime
    updated_at: datetime


class LibrarianProviderUpdateValues(TypedDict, total=False, closed=True):
    """Explicit patchable librarian provider fields before persistence mapping."""

    name: str
    provider_type: ProviderType
    auth_type: AuthType
    enabled: bool
    config: JSONObject


class LibrarianProviderUpdateRecord(TypedDict, total=False, closed=True):
    """Persistence fields for patching a librarian provider row."""

    name: str
    provider_type: str
    auth_type: str
    enabled: bool
    config: JSONObject


class LibrarianProviderPatchPayload(TypedDict, total=False, closed=True):
    """Service-layer provider patch payload including optional secret inputs."""

    name: str
    provider_type: ProviderType | str
    auth_type: AuthType | str
    enabled: bool
    config: JSONObject
    api_key: str
    oauth_access_token: str


class LibrarianProviderTestPayload(TypedDict, closed=True):
    """Public provider connection-test result payload."""

    provider_id: str
    ok: bool
    message: str


type LibrarianProviderPayloadList = list[LibrarianProviderPayload]
