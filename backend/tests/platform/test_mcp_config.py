"""Required mcp configuration contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.config_test_data import mcp_config_values

from app.platform.config.mcp_config import McpConfig


def test_mcp_config_missing_field_error_does_not_expose_other_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation errors must redact supplied secrets when another key is missing."""
    monkeypatch.delenv("SERVICE_MCP_AUTH_MODE", raising=False)
    values = mcp_config_values(mcp_local_approval_key="sensitive-operator-key")
    values.pop("mcp_auth_mode")

    with pytest.raises(ValidationError) as failure:
        McpConfig(_env_file=None, **values)

    assert "sensitive-operator-key" not in str(failure.value)


def test_mcp_config_rejects_incomplete_mcp_oauth_config() -> None:
    """OAuth mode should fail closed when issuer metadata is missing."""
    with pytest.raises(ValueError, match="MCP OAuth mode requires"):
        McpConfig(_env_file=None, **mcp_config_values(mcp_auth_mode="oauth2"))


def test_mcp_config_accepts_complete_mcp_oauth_config() -> None:
    """OAuth mode should normalize resource-server metadata settings."""
    config = McpConfig(
        _env_file=None,
        **mcp_config_values(
            mcp_auth_mode="oauth2",
            mcp_oauth_issuer="https://auth.example.com",
            mcp_oauth_audience="https://mcp.example.com/mcp",
            mcp_oauth_jwks_url="https://auth.example.com/.well-known/jwks.json",
            mcp_oauth_authorization_servers=(
                "https://auth.example.com, https://backup.example.com"
            ),
            mcp_oauth_required_scope="alexandria:mcp alexandria:read",
        ),
    )

    assert config.mcp_oauth_authorization_server_urls() == (
        "https://auth.example.com",
        "https://backup.example.com",
    )
    assert config.mcp_oauth_required_scopes() == (
        "alexandria:mcp",
        "alexandria:read",
    )
