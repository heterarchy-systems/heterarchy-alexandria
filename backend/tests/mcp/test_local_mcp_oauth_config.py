"""Configuration invariants for Alexandria's local MCP OAuth mode."""

from __future__ import annotations

import pytest
from tests.config_test_data import mcp_config_values, set_config_environment

from app.platform.config.mcp_config import McpConfig


def test_local_oauth_mode_requires_issuer_resource_and_approval_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local token issuance must fail closed when public metadata is incomplete."""
    set_config_environment(monkeypatch, "SERVICE_", mcp_config_values())
    for name in (
        "SERVICE_MCP_OAUTH_ISSUER",
        "SERVICE_MCP_OAUTH_RESOURCE",
        "SERVICE_MCP_LOCAL_APPROVAL_KEY",
        "ALEXANDRIA_OPERATOR_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="MCP local OAuth mode requires"):
        McpConfig(_env_file=None, **mcp_config_values(mcp_auth_mode="local_oauth2"))


def test_local_oauth_mode_accepts_legacy_operator_key_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing local operator configuration should approve browser OAuth flows."""
    set_config_environment(
        monkeypatch,
        "SERVICE_",
        mcp_config_values(
            mcp_auth_mode="local_oauth2",
            mcp_oauth_issuer="http://127.0.0.1:8000",
            mcp_oauth_resource="http://127.0.0.1:8000/mcp",
        ),
    )
    monkeypatch.delenv("SERVICE_MCP_LOCAL_APPROVAL_KEY", raising=False)
    monkeypatch.setenv("ALEXANDRIA_OPERATOR_API_KEY", "o" * 32)

    config = McpConfig(_env_file=None)

    assert config.mcp_local_approval_key_value() == "o" * 32
    assert config.mcp_local_oauth_default_scopes() == (
        "alexandria:mcp",
        "offline_access",
    )


def test_local_oauth_mode_rejects_remote_plain_http_and_cross_origin_resource() -> None:
    """Only localhost may use HTTP and issuer/resource must share an origin."""
    with pytest.raises(ValueError, match="HTTPS outside localhost"):
        McpConfig(
            _env_file=None,
            **mcp_config_values(
                mcp_auth_mode="local_oauth2",
                mcp_oauth_issuer="http://mcp.example.com",
                mcp_oauth_resource="http://mcp.example.com/mcp",
                mcp_local_approval_key="o" * 32,
            ),
        )

    with pytest.raises(ValueError, match="share one origin"):
        McpConfig(
            _env_file=None,
            **mcp_config_values(
                mcp_auth_mode="local_oauth2",
                mcp_oauth_issuer="https://auth.example.com",
                mcp_oauth_resource="https://mcp.example.com/mcp",
                mcp_local_approval_key="o" * 32,
            ),
        )


def test_local_oauth_mode_rejects_short_approval_key() -> None:
    """Browser approval credentials must resist online guessing."""
    with pytest.raises(ValueError, match="at least 24 characters"):
        McpConfig(
            _env_file=None,
            **mcp_config_values(
                mcp_auth_mode="local_oauth2",
                mcp_oauth_issuer="https://mcp.example.com",
                mcp_oauth_resource="https://mcp.example.com/mcp",
                mcp_local_approval_key="too-short",
            ),
        )
