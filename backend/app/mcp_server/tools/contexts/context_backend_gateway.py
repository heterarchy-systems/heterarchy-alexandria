"""Context Vault MCP HTTP gateway functions."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import (
    _path_segment,
)
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextSearchRequest,
)
from app.memory.interface.schemas.context.context_schema import ContextSupersedeRequest
from app.shared.serialization.model_codec import schema_payload
from app.shared.types.extra_types import JSONValue


async def alexandria_search(
    client: AlexandriaApiClient,
    request: ContextSearchRequest,
) -> JSONValue:
    """Search Context Vault and return a Context Pack.

    Args:
        client: Backend HTTP client.
        request: Validated Context search boundary contract.

    Returns:
        Backend Context Pack response.
    """
    payload = schema_payload(request, exclude_none=True)
    if payload.get("include_scopes") == []:
        del payload["include_scopes"]
    if payload.get("include_lifecycle_statuses") == []:
        del payload["include_lifecycle_statuses"]
    if payload.get("prefer_memory_functions") == []:
        del payload["prefer_memory_functions"]
    response = await client.post("/memory/contexts/retrieval/search", payload)
    return response


async def alexandria_archive_context(
    client: AlexandriaApiClient, context_id: str
) -> JSONValue:
    """Archive a context without hard deleting it.

    Args:
        client: Backend HTTP client.
        context_id: Context identifier.

    Returns:
        Archived context response.
    """
    response = await client.post(
        f"/memory/contexts/{_path_segment(context_id)}/archive", {}
    )
    return response


async def alexandria_supersede_context(
    client: AlexandriaApiClient,
    context_id: str,
    replacement_context_id: str,
) -> JSONValue:
    """Link one canonical context to an existing replacement.

    Args:
        client: Backend HTTP client.
        context_id: Context identifier to supersede.
        replacement_context_id: Replacement Context identifier.

    Returns:
        Superseded and replacement context response.
    """
    request = ContextSupersedeRequest(
        replacement_context_id=replacement_context_id,
    )
    response = await client.post(
        f"/memory/contexts/{_path_segment(context_id)}/supersede",
        schema_payload(request),
    )
    return response


async def alexandria_delete_context(
    client: AlexandriaApiClient, context_id: str
) -> JSONValue:
    """Hard delete one context.

    Args:
        client: Backend HTTP client.
        context_id: Context identifier.

    Returns:
        Backend delete response, typically None for HTTP 204.
    """
    response = await client.delete(f"/memory/contexts/{_path_segment(context_id)}")
    return response


async def alexandria_rag_status(client: AlexandriaApiClient) -> JSONValue:
    """Read Context RAG dependency status.

    Args:
        client: Backend HTTP client.

    Returns:
        RAG health response.
    """
    response = await client.get("/memory/contexts/rag/status")
    return response
