"""Librarian provider schema payload conversion tests."""

from __future__ import annotations

from app.connections.interface.schemas.librarian.provider_schema import (
    LibrarianProviderPatchRequest,
)
from app.shared.serialization.orjson_codec import dumps_json


def test_provider_patch_payload_excludes_absent_and_null_secret_fields() -> None:
    """Provider patch conversion should include only actionable non-null fields."""
    request = LibrarianProviderPatchRequest(enabled=False, api_key=None)

    assert request.to_payload() == {"enabled": False}


def test_provider_patch_payload_serializes_enum_values_for_application_boundary() -> (
    None
):
    """Provider patch conversion should use stable enum values from Pydantic."""
    request = LibrarianProviderPatchRequest.model_validate_json(
        dumps_json({"provider_type": "OPENAI", "auth_type": "API_KEY"})
    )

    assert request.to_payload() == {
        "provider_type": "OPENAI",
        "auth_type": "API_KEY",
    }
