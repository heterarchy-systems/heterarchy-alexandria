"""Register Obsidian note and graph MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import DEFAULT_CONTEXT_SEARCH_LIMIT
from app.mcp_server.tools.obsidian.obsidian_backend_gateway import (
    alexandria_check_path_exists,
    alexandria_create_note,
    alexandria_get_related_notes,
    alexandria_read_note,
    alexandria_resolve_canonical_identity,
    alexandria_update_note,
    alexandria_upsert_note,
    alexandria_upsert_report_bundle,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianWriteMatchBy,
)
from app.shared.types.extra_types import JSONValue


def register_obsidian_note_tools(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register Obsidian note and graph MCP tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_read_note")
    async def _tool_read_note(
        note_id: str | None = None,
        path: str | None = None,
    ) -> JSONValue:
        """Read one Alexandria-managed Obsidian note by id or path.

        Args:
            note_id: Identifier for note.
            path: Path used by this operation.

        Returns:
            JSONValue result produced by tool read note.
        """
        return await alexandria_read_note(api_client, note_id, path)

    @server.tool(name="alexandria_check_path_exists")
    async def _tool_check_path_exists(path: str) -> JSONValue:
        """Check one exact managed path and return existence, id, and index status.

        Args:
            path: Path used by this operation.

        Returns:
            JSONValue result produced by tool check path exists.
        """
        return await alexandria_check_path_exists(api_client, path)

    @server.tool(name="alexandria_resolve_canonical_identity")
    async def _tool_resolve_canonical_identity(
        project: str,
        report: str,
        date: str,
        entity: str,
        edition: str | None = None,
    ) -> JSONValue:
        """Resolve report aliases and logical identity into one canonical path.

        Args:
            project: Project used by this operation.
            report: Report used by this operation.
            date: Date used by this operation.
            entity: Entity used by this operation.
            edition: Edition used by this operation.

        Returns:
            JSONValue result produced by tool resolve canonical identity.
        """
        return await alexandria_resolve_canonical_identity(
            api_client,
            project,
            report,
            date,
            entity,
            edition,
        )

    @server.tool(name="alexandria_get_related_notes")
    async def _tool_get_related_notes(
        note_id: str | None = None,
        path: str | None = None,
        limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
    ) -> JSONValue:
        """Read graph-related Obsidian notes by id or path.

        Args:
            note_id: Identifier for note.
            path: Path used by this operation.
            limit: Maximum number of items to process or return.

        Returns:
            JSONValue result produced by tool get related notes.
        """
        return await alexandria_get_related_notes(api_client, note_id, path, limit)

    @server.tool(name="alexandria_create_note")
    async def _tool_create_note(
        title: str,
        body: str,
        alexandria_type: AlexandriaNoteType,
        match_by: ObsidianWriteMatchBy,
        note_id: str | None = None,
        path: str | None = None,
        project: str | None = None,
        tags: list[str] | str | None = None,
        status: str = "active",
        source: str = "mcp",
        frontmatter: dict[str, JSONValue] | None = None,
        frontmatter_mode: ObsidianFrontmatterMode = ObsidianFrontmatterMode.MERGE,
    ) -> JSONValue:
        """Create only; fail before mutation when the exact id or path exists.

        Args:
            title: Title used by this operation.
            body: Body used by this operation.
            alexandria_type: Alexandria type used by this operation.
            match_by: Match by used by this operation.
            note_id: Identifier for note.
            path: Path used by this operation.
            project: Project used by this operation.
            tags: Tags used by this operation.
            status: Status value used by this operation.
            source: Source used by this operation.
            frontmatter: Frontmatter used by this operation.
            frontmatter_mode: Frontmatter mode used by this operation.

        Returns:
            JSONValue result produced by tool create note.
        """
        return await alexandria_create_note(
            api_client,
            title,
            body,
            alexandria_type.value,
            match_by.value,
            note_id,
            path,
            project,
            tags,
            status,
            source,
            frontmatter,
            frontmatter_mode.value,
        )

    @server.tool(name="alexandria_update_note")
    async def _tool_update_note(
        title: str,
        body: str,
        alexandria_type: AlexandriaNoteType,
        match_by: ObsidianWriteMatchBy,
        note_id: str | None = None,
        path: str | None = None,
        project: str | None = None,
        tags: list[str] | str | None = None,
        status: str | None = None,
        source: str | None = None,
        frontmatter: dict[str, JSONValue] | None = None,
        frontmatter_mode: ObsidianFrontmatterMode = ObsidianFrontmatterMode.MERGE,
        expected_content_hash: str | None = None,
    ) -> JSONValue:
        """Update by exact id or path; never infer a move or replacement target.

        Args:
            title: Title used by this operation.
            body: Body used by this operation.
            alexandria_type: Alexandria type used by this operation.
            match_by: Match by used by this operation.
            note_id: Identifier for note.
            path: Path used by this operation.
            project: Project used by this operation.
            tags: Tags used by this operation.
            status: Status value used by this operation.
            source: Source used by this operation.
            frontmatter: Frontmatter used by this operation.
            frontmatter_mode: Frontmatter mode used by this operation.
            expected_content_hash: Expected content hash used for validation.

        Returns:
            JSONValue result produced by tool update note.
        """
        return await alexandria_update_note(
            api_client,
            title,
            body,
            alexandria_type.value,
            match_by.value,
            note_id,
            path,
            project,
            tags,
            status,
            source,
            frontmatter,
            frontmatter_mode.value,
            expected_content_hash,
        )

    @server.tool(name="alexandria_upsert_note")
    async def _tool_upsert_note(
        title: str,
        body: str,
        alexandria_type: AlexandriaNoteType,
        match_by: ObsidianWriteMatchBy,
        note_id: str | None = None,
        path: str | None = None,
        project: str | None = None,
        tags: list[str] | str | None = None,
        status: str | None = None,
        source: str | None = None,
        frontmatter: dict[str, JSONValue] | None = None,
        frontmatter_mode: ObsidianFrontmatterMode = ObsidianFrontmatterMode.MERGE,
        expected_content_hash: str | None = None,
    ) -> JSONValue:
        """Create or update by one exact selector and reject identity conflicts.

        Args:
            title: Title used by this operation.
            body: Body used by this operation.
            alexandria_type: Alexandria type used by this operation.
            match_by: Match by used by this operation.
            note_id: Identifier for note.
            path: Path used by this operation.
            project: Project used by this operation.
            tags: Tags used by this operation.
            status: Status value used by this operation.
            source: Source used by this operation.
            frontmatter: Frontmatter used by this operation.
            frontmatter_mode: Frontmatter mode used by this operation.
            expected_content_hash: Expected content hash used for validation.

        Returns:
            JSONValue result produced by tool upsert note.
        """
        return await alexandria_upsert_note(
            api_client,
            title,
            body,
            alexandria_type.value,
            match_by.value,
            note_id,
            path,
            project,
            tags,
            status,
            source,
            frontmatter,
            frontmatter_mode.value,
            expected_content_hash,
        )

    @server.tool(name="alexandria_upsert_report_bundle")
    async def _tool_upsert_report_bundle(
        idempotency_key: str,
        source: dict[str, JSONValue],
        graph_owners: list[dict[str, JSONValue]],
        reindex: bool = True,
        verify_index_status: bool = True,
        verify_incoming_edges: bool = True,
        verify_duplicates: bool = True,
    ) -> JSONValue:
        """Idempotently upsert Source and owner links, rebuild, and verify graph.

        Args:
            idempotency_key: Idempotency key used by this operation.
            source: Source used by this operation.
            graph_owners: Graph owners used by this operation.
            reindex: Reindex used by this operation.
            verify_index_status: Verify index status used by this operation.
            verify_incoming_edges: Verify incoming edges used by this operation.
            verify_duplicates: Verify duplicates used by this operation.

        Returns:
            JSONValue result produced by tool upsert report bundle.
        """
        return await alexandria_upsert_report_bundle(
            api_client,
            idempotency_key,
            source,
            graph_owners,
            reindex,
            verify_index_status,
            verify_incoming_edges,
            verify_duplicates,
        )
