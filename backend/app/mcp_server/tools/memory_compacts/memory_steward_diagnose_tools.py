"""Memory Steward HTTP adapters for diagnose and seal."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.shared.types.extra_types import JSONValue


async def alexandria_memory_steward_diagnose(client: AlexandriaApiClient) -> JSONValue:
    """Return composed Memory Steward diagnostics from the backend authority.

    Args:
        client: Backend HTTP client.

    Returns:
        Diagnose result with overall status and per-issue detail references.
    """
    return await client.get("/operations/memory-steward/diagnose")


async def alexandria_memory_steward_seal(client: AlexandriaApiClient) -> JSONValue:
    """Return the seal verification verdict from the backend authority.

    Args:
        client: Backend HTTP client.

    Returns:
        Seal result with overall status and residual diagnostics.
    """
    return await client.get("/operations/memory-steward/seal")
