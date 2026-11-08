"""Shared context construction for maintenance CLI commands."""

from __future__ import annotations

from app.cli.maintenance_gateway import MaintenanceGateway
from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.platform.config.mcp_config import McpApiConfig


def build_maintenance_gateway() -> MaintenanceGateway:
    """Build a maintenance gateway from environment-backed API settings.

    Returns:
        Maintenance gateway bound to the configured Alexandria backend.
    """
    return MaintenanceGateway(AlexandriaApiClient(McpApiConfig.from_env()))
