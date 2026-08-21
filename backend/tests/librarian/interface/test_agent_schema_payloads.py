"""Agent schema payload conversion tests."""

from __future__ import annotations

import pytest
from app.librarian.interface.schemas.agent.agent_schema import AgentPatchRequest
from app.shared.serialization.orjson_codec import dumps_json
from pydantic import ValidationError


def test_agent_patch_payload_preserves_nullable_clear_requests() -> None:
    """Agent patch conversion should include explicit nullable field clears."""
    request = AgentPatchRequest(
        description=None,
        preferred_librarian_provider=None,
        librarian_enabled=False,
    )

    assert request.to_payload() == {
        "description": None,
        "preferred_librarian_provider": None,
        "librarian_enabled": False,
    }


def test_agent_patch_payload_serializes_enum_values_for_application_boundary() -> None:
    """Agent patch conversion should use stable enum values from Pydantic."""
    request = AgentPatchRequest.model_validate_json(
        dumps_json({"librarian_role": "QUALITY_REVIEWER"})
    )

    assert request.to_payload() == {"librarian_role": "QUALITY_REVIEWER"}


def test_agent_patch_payload_rejects_null_required_fields() -> None:
    """Agent patch validation should reject explicit nulls for required fields."""
    with pytest.raises(ValidationError, match="capabilities cannot be null"):
        AgentPatchRequest(capabilities=None)
