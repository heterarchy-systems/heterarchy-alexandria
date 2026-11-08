"""Register focused Memory Steward readiness and compaction MCP tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.memory_compacts.memory_steward_diagnose_tools import (
    alexandria_memory_steward_diagnose,
    alexandria_memory_steward_seal,
)
from app.mcp_server.tools.memory_compacts.memory_steward_readiness_tools import (
    alexandria_memory_steward_readiness,
    alexandria_memory_steward_refresh_current_compact,
)
from app.shared.types.extra_types import JSONValue


def register_memory_steward_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register Memory Steward operational tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_memory_steward_readiness")
    async def _tool_memory_steward_readiness(
        project: str | None = None,
        max_compact_age_days: int = 30,
    ) -> JSONValue:
        """Return RAG, Memory Compact, and vault-review readiness.

        Args:
            project: Optional project scope filter for the current compact.
            max_compact_age_days: Maximum acceptable age in days for the current compact.

        Returns:
            Readiness summary with RAG health, compact review status, warnings, and next actions.
        """
        return await alexandria_memory_steward_readiness(
            api_client,
            project=project,
            max_compact_age_days=max_compact_age_days,
        )

    @server.tool(name="alexandria_memory_steward_refresh_current_compact")
    async def _tool_memory_steward_refresh_current_compact(
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
        draft_only: bool = False,
        source_refs: Sequence[Mapping[str, JSONValue]] | None = None,
        semantic_template: Mapping[str, str] | str | None = None,
        final_markdown: str | None = None,
    ) -> JSONValue:
        """Plan or apply a CURRENT Memory Compact refresh from readiness evidence.

        Args:
            project: Optional project scope filter for the compact.
            max_compact_age_days: Maximum acceptable age in days for the current compact.
            apply: Whether to persist the generated compact when refresh is needed.
            force: Whether to refresh even when the current compact is already fresh.
            covered_to: Optional ISO-8601 coverage end timestamp.
            draft_only: Create a DRAFT for semantic editing instead of
                promoting CURRENT directly.
            source_refs: Optional project-specific source references.
            semantic_template: Optional project-specific section content.
            final_markdown: Optional final agent-edited Markdown body.

        Returns:
            Refresh plan, optional creation result, and post-refresh readiness summary.
        """
        return await alexandria_memory_steward_refresh_current_compact(
            api_client,
            project=project,
            max_compact_age_days=max_compact_age_days,
            apply=apply,
            force=force,
            covered_to=covered_to,
            draft_only=draft_only,
            source_refs=source_refs,
            semantic_template=semantic_template,
            final_markdown=final_markdown,
        )

    @server.tool(name="alexandria_memory_steward_diagnose")
    async def _tool_memory_steward_diagnose() -> JSONValue:
        """Compose readiness evidence into Memory Steward diagnostics.

        Returns:
            Diagnose result with overall status and per-issue detail refs.
        """
        return await alexandria_memory_steward_diagnose(api_client)

    @server.tool(name="alexandria_memory_steward_seal")
    async def _tool_memory_steward_seal() -> JSONValue:
        """Run the final readiness verification for one memory circulation.

        Returns:
            Seal result with overall status and residual diagnostics.
        """
        return await alexandria_memory_steward_seal(api_client)
