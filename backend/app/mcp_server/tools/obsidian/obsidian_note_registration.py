"""Register Obsidian note and graph MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import DEFAULT_CONTEXT_SEARCH_LIMIT
from app.mcp_server.tools.obsidian.frontmatter_repair_backend_gateway import (
    alexandria_repair_frontmatter,
)
from app.mcp_server.tools.obsidian.obsidian_backend_gateway import (
    ObsidianNoteBatchGateway,
    ObsidianNoteReadGateway,
    ObsidianNoteWriteGateway,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianContextLifecycleStatus,
    ObsidianFrontmatterMode,
    ObsidianWriteMatchBy,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_source_schema import (
    ObsidianFrontmatterRepairRequest,
    ObsidianFrontmatterRepairResponse,
)
from app.shared.types.extra_types import JSONObject, JSONValue


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
            note_id: Canonical note identifier, if reading by id.
            path: Vault-relative Markdown path, if reading by path.

        Returns:
            Parsed note metadata, frontmatter, and Markdown body payload.
        """
        return await ObsidianNoteReadGateway.read_note(api_client, note_id, path)

    @server.tool(name="alexandria_read_note_raw")
    async def _tool_read_note_raw(
        note_id: str | None = None,
        path: str | None = None,
    ) -> JSONValue:
        """Read one note's raw source even when frontmatter fails to parse.

        Args:
            note_id: Canonical note identifier, if reading by id.
            path: Vault-relative Markdown path, if reading by path.

        Returns:
            Raw Markdown content and current content hash for CAS repair.
        """
        return await ObsidianNoteReadGateway.read_note_raw(api_client, note_id, path)

    @server.tool(name="alexandria_repair_frontmatter")
    async def _tool_repair_frontmatter(
        request: ObsidianFrontmatterRepairRequest,
    ) -> ObsidianFrontmatterRepairResponse:
        """Repair one note's frontmatter while preserving durable body bytes.

        Use this instead of alexandria_repair_note_raw when only the
        frontmatter is stale or malformed: the body bytes survive exactly,
        server-owned caller fields are rejected, and redaction
        placeholders are refused.

        Args:
            request: Validated frontmatter repair request.

        Returns:
            Before/after hash evidence with body preservation proof.
        """
        return await alexandria_repair_frontmatter(api_client, request)

    @server.tool(name="alexandria_repair_note_raw")
    async def _tool_repair_note_raw(
        path: str,
        expected_content_hash: str,
        raw_content: str,
    ) -> JSONValue:
        """Replace one note's raw source after CAS and parse validation.

        Use together with alexandria_read_note_raw to recover a malformed
        note in place: read the raw text, fix the frontmatter or body, and
        submit the full replacement against the current content hash.

        Args:
            path: Vault-relative Markdown path of the note to repair.
            expected_content_hash: Content hash of the current raw bytes.
            raw_content: Full replacement Markdown source.

        Returns:
            Repaired note metadata and updated content hash.
        """
        return await ObsidianNoteWriteGateway.repair_note_raw(
            api_client,
            path,
            expected_content_hash,
            raw_content,
        )

    @server.tool(name="alexandria_check_path_exists")
    async def _tool_check_path_exists(path: str) -> JSONValue:
        """Check one exact managed path and return existence, id, and index status.

        Args:
            path: Vault-relative Markdown path to inspect.

        Returns:
            Path existence, canonical note id, and current index status payload.
        """
        return await ObsidianNoteReadGateway.check_path_exists(api_client, path)

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
            project: Project scope slug or name.
            report: Report type or alias to normalize.
            date: ISO date string for the report edition.
            entity: Target entity or subject identifier.
            edition: Optional edition qualifier when multiple runs exist.

        Returns:
            Canonical logical identity, resolved vault path, and existing note status.
        """
        return await ObsidianNoteReadGateway.resolve_canonical_identity(
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
            note_id: Canonical note identifier, if querying by id.
            path: Vault-relative Markdown path, if querying by path.
            limit: Maximum number of related notes to return.

        Returns:
            Graph-related note records connected to the target note.
        """
        return await ObsidianNoteReadGateway.get_related_notes(
            api_client, note_id, path, limit
        )

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
        status: str = ObsidianContextLifecycleStatus.ACTIVE.value,
        source: str = "mcp",
        frontmatter: dict[str, JSONValue] | None = None,
        frontmatter_mode: ObsidianFrontmatterMode = ObsidianFrontmatterMode.MERGE,
        idempotency_key: str | None = None,
    ) -> JSONValue:
        """Create once per request identity; reject another request at an existing target.

        Args:
            title: Human-readable note title.
            body: Markdown body content without frontmatter fences.
            alexandria_type: Canonical Alexandria note classification.
            match_by: Selector mode (id or path) used to guard against collisions.
            note_id: Explicit note identifier when matching or assigning by id.
            path: Vault-relative destination path under the Alexandria root.
            project: Optional project scope associated with the note.
            tags: Optional tag list or comma-separated tag string.
            status: Lifecycle status recorded in frontmatter.
            source: Provenance source label recorded in frontmatter.
            frontmatter: Additional custom frontmatter key-value pairs.
            frontmatter_mode: Merge or replace strategy for custom frontmatter.
            idempotency_key: Retry-stable mutation identity; retain it after a lost response.

        Returns:
            Created note payload with canonical id, path, and content hash.
        """
        return await ObsidianNoteWriteGateway.create_note(
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
            idempotency_key=idempotency_key,
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
        idempotency_key: str | None = None,
    ) -> JSONValue:
        """Update by exact id or path; never infer a move or replacement target.

        Args:
            title: Updated human-readable note title.
            body: Updated Markdown body content without frontmatter fences.
            alexandria_type: Canonical Alexandria note classification.
            match_by: Exact selector mode (id or path) locating the existing note.
            note_id: Target note identifier when matching by id.
            path: Target vault-relative Markdown path when matching by path.
            project: Optional updated project scope.
            tags: Optional updated tag list or comma-separated tag string.
            status: Optional updated lifecycle status.
            source: Optional updated provenance source label.
            frontmatter: Optional custom frontmatter fields to merge or replace.
            frontmatter_mode: Merge or replace strategy for custom frontmatter.
            expected_content_hash: Current content hash required for CAS verification.
            idempotency_key: Retry-stable mutation identity; retain it after a lost response.

        Returns:
            Updated note payload with canonical id, path, and new content hash.
        """
        return await ObsidianNoteWriteGateway.update_note(
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
            idempotency_key=idempotency_key,
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
        idempotency_key: str | None = None,
    ) -> JSONValue:
        """Create or update by one exact selector and reject identity conflicts.

        Args:
            title: Human-readable note title.
            body: Markdown body content without frontmatter fences.
            alexandria_type: Canonical Alexandria note classification.
            match_by: Exact selector mode (id or path) used to locate or create the note.
            note_id: Target note identifier when matching by id.
            path: Target vault-relative Markdown path when matching by path.
            project: Optional project scope associated with the note.
            tags: Optional tag list or comma-separated tag string.
            status: Optional lifecycle status recorded in frontmatter.
            source: Optional provenance source label recorded in frontmatter.
            frontmatter: Optional custom frontmatter fields to merge or replace.
            frontmatter_mode: Merge or replace strategy for custom frontmatter.
            expected_content_hash: Current content hash when updating an existing note.
            idempotency_key: Retry-stable mutation identity; retain it after a lost response.

        Returns:
            Upserted note payload with canonical id, path, and content hash.
        """
        return await ObsidianNoteWriteGateway.upsert_note(
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
            idempotency_key=idempotency_key,
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
            idempotency_key: Retry-stable bundle mutation identity.
            source: Source note specification to create or update.
            graph_owners: Owner notes and wikilink updates referencing the source note.
            reindex: Whether to reindex modified notes and rebuild the graph projection.
            verify_index_status: Whether to verify all bundle notes indexed cleanly.
            verify_incoming_edges: Whether to verify expected incoming graph edges exist.
            verify_duplicates: Whether to check for duplicate identity or content conflicts.

        Returns:
            Bundle execution receipt with source, owner, and verification results.
        """
        return await ObsidianNoteWriteGateway.upsert_report_bundle(
            api_client,
            idempotency_key,
            source,
            graph_owners,
            reindex,
            verify_index_status,
            verify_incoming_edges,
            verify_duplicates,
        )

    @server.tool(name="alexandria_batch_read_notes")
    async def _tool_batch_read_notes(
        selectors: list[dict[str, str | None]],
    ) -> JSONValue:
        """Read many notes independently by path or note_id.

        Args:
            selectors: List of note selectors, each with path or note_id.

        Returns:
            Per-item read results. One item's failure does not fail the batch.
        """
        return await ObsidianNoteBatchGateway.batch_read_notes(api_client, selectors)

    @server.tool(name="alexandria_batch_validate_note_links")
    async def _tool_batch_validate_note_links(
        selectors: list[dict[str, str | None]],
    ) -> JSONValue:
        """Validate outgoing links for many notes independently.

        Args:
            selectors: List of note selectors.

        Returns:
            Per-item validation outcomes. One item's failure does not fail the batch.
        """
        return await ObsidianNoteBatchGateway.batch_validate_note_links(
            api_client, selectors
        )

    @server.tool(name="alexandria_batch_write_notes")
    async def _tool_batch_write_notes(
        operations: list[JSONObject],
    ) -> JSONValue:
        """Apply many independent CAS writes with per-item outcomes.

        Args:
            operations: List of write operations with per-item CAS.

        Returns:
            Per-item write outcomes. One item's conflict does not fail the batch.
        """
        return await ObsidianNoteBatchGateway.batch_write_notes(api_client, operations)
