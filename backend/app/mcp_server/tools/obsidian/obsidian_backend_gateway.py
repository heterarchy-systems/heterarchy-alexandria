"""Obsidian search, note, graph, and vault MCP HTTP gateway classes."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import (
    DEFAULT_CONTEXT_SEARCH_LIMIT,
    bounded_search_limit,
    items_or_empty,
    path_segment,
)
from app.mcp_server.type_validate.obsidian.obsidian_search_contracts import (
    compact_vault_search_response,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianContextLifecycleStatus,
    ObsidianFrontmatterMode,
)
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_known_frontmatter_metadata,
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class ObsidianNoteReadGateway:
    """MCP HTTP gateway for single-note reads, path lookups, and graph neighbors."""

    @staticmethod
    async def read_note(
        client: AlexandriaApiClient,
        note_id: str | None = None,
        path: str | None = None,
    ) -> JSONValue:
        """Read one Alexandria-managed Obsidian note by id or path.

        Args:
            client: Backend HTTP client.
            note_id: Stable note id.
            path: Vault-relative path.

        Returns:
            Backend note response.

        Raises:
            ValueError: If neither note_id nor path is provided.
        """
        if path is not None:
            return await client.get("/obsidian/notes/by-path", params={"path": path})
        if note_id is None:
            raise ValueError("note_id or path is required")
        return await client.get(f"/obsidian/notes/{path_segment(note_id)}")

    @staticmethod
    async def read_note_raw(
        client: AlexandriaApiClient,
        note_id: str | None = None,
        path: str | None = None,
    ) -> JSONValue:
        """Read one note's raw source even when its frontmatter fails to parse.

        Args:
            client: Backend HTTP client.
            note_id: Stable note id.
            path: Vault-relative path.

        Returns:
            Backend raw note read response.

        Raises:
            ValueError: If neither note_id nor path is provided.
        """
        if path is None and note_id is None:
            raise ValueError("note_id or path is required")
        params: JSONObject = {}
        if path is not None:
            params["path"] = path
        if note_id is not None:
            params["note_id"] = note_id
        return await client.get("/obsidian/notes/raw", params=params)

    @staticmethod
    async def check_path_exists(
        client: AlexandriaApiClient,
        path: str,
    ) -> JSONValue:
        """Check one exact managed path without fuzzy retrieval.

        Args:
            client: Backend HTTP client.
            path: Vault-relative Markdown path to check.

        Returns:
            Backend path existence check response.
        """
        return await client.get("/obsidian/notes/check-path", params={"path": path})

    @staticmethod
    async def resolve_canonical_identity(
        client: AlexandriaApiClient,
        project: str,
        report: str,
        date: str,
        entity: str,
        edition: str | None = None,
    ) -> JSONValue:
        """Resolve a report identity through existing metadata and declared aliases.

        Args:
            client: Backend HTTP client.
            project: Project slug for the report identity.
            report: Report type or family name.
            date: Report date string.
            entity: Target entity identifier.
            edition: Optional edition qualifier.

        Returns:
            Backend canonical identity resolution response.
        """
        payload: JSONObject = {
            "project": project,
            "report": report,
            "date": date,
            "entity": entity,
        }
        if edition is not None:
            payload["edition"] = edition
        return await client.post("/obsidian/notes/resolve-canonical-identity", payload)

    @staticmethod
    async def get_related_notes(
        client: AlexandriaApiClient,
        note_id: str | None = None,
        path: str | None = None,
        limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
    ) -> JSONValue:
        """Read graph-related Obsidian notes by id or path.

        Args:
            client: Backend HTTP client.
            note_id: Stable note id.
            path: Vault-relative note path.
            limit: Maximum related notes.

        Returns:
            Backend related notes response.

        Raises:
            ValueError: If neither note_id nor path is provided.
        """
        bounded_limit = bounded_search_limit(limit)
        if path is not None:
            return await client.get(
                "/obsidian/notes/by-path/related",
                params={"path": path, "limit": bounded_limit},
            )
        if note_id is None:
            raise ValueError("note_id or path is required")
        return await client.get(
            f"/obsidian/notes/{path_segment(note_id)}/related",
            params={"limit": bounded_limit},
        )


class ObsidianNoteWriteGateway:
    """MCP HTTP gateway for single-note mutations, raw repair, and report bundles."""

    @staticmethod
    async def create_note(
        client: AlexandriaApiClient,
        title: str,
        body: str,
        alexandria_type: str,
        match_by: str,
        note_id: str | None = None,
        path: str | None = None,
        project: str | None = None,
        tags: list[str] | str | None = None,
        status: str = ObsidianContextLifecycleStatus.ACTIVE.value,
        source: str = "mcp",
        frontmatter: JSONObject | None = None,
        frontmatter_mode: str = ObsidianFrontmatterMode.MERGE.value,
        idempotency_key: str | None = None,
    ) -> JSONValue:
        """Create once per request identity, rejecting another request at an existing target.

        Args:
            client: Backend HTTP client.
            title: Note title.
            body: Markdown body content.
            alexandria_type: Managed note type.
            match_by: Selector matching mode.
            note_id: Optional stable note identifier.
            path: Optional vault-relative path.
            project: Optional project slug.
            tags: Optional tag list or comma-separated tags.
            status: Initial note lifecycle status.
            source: Note mutation source label.
            frontmatter: Optional custom frontmatter mapping.
            frontmatter_mode: Frontmatter merge strategy.
            idempotency_key: Retry-stable identity for the canonical write receipt.

        Returns:
            Backend created note response.
        """
        return await _ObsidianGatewayPayloadHelper.write_note(
            client,
            endpoint="/obsidian/notes/create",
            title=title,
            body=body,
            alexandria_type=alexandria_type,
            match_by=match_by,
            note_id=note_id,
            path=path,
            project=project,
            tags=tags,
            status=status,
            source=source,
            frontmatter=frontmatter,
            frontmatter_mode=frontmatter_mode,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    async def update_note(
        client: AlexandriaApiClient,
        title: str,
        body: str,
        alexandria_type: str,
        match_by: str,
        note_id: str | None = None,
        path: str | None = None,
        project: str | None = None,
        tags: list[str] | str | None = None,
        status: str | None = None,
        source: str | None = None,
        frontmatter: JSONObject | None = None,
        frontmatter_mode: str = ObsidianFrontmatterMode.MERGE.value,
        expected_content_hash: str | None = None,
        idempotency_key: str | None = None,
    ) -> JSONValue:
        """Update an existing exact id or path without moving it implicitly.

        Args:
            client: Backend HTTP client.
            title: Updated note title.
            body: Updated Markdown body content.
            alexandria_type: Managed note type.
            match_by: Selector matching mode.
            note_id: Optional stable note identifier.
            path: Optional vault-relative path.
            project: Optional project slug.
            tags: Optional tag list or comma-separated tags.
            status: Optional updated lifecycle status.
            source: Optional mutation source label.
            frontmatter: Optional custom frontmatter mapping.
            frontmatter_mode: Frontmatter merge strategy.
            expected_content_hash: Expected current content hash for CAS validation.
            idempotency_key: Retry-stable identity for the canonical write receipt.

        Returns:
            Backend updated note response.
        """
        return await _ObsidianGatewayPayloadHelper.write_note(
            client,
            endpoint="/obsidian/notes/update",
            title=title,
            body=body,
            alexandria_type=alexandria_type,
            match_by=match_by,
            note_id=note_id,
            path=path,
            project=project,
            tags=tags,
            status=status,
            source=source,
            frontmatter=frontmatter,
            frontmatter_mode=frontmatter_mode,
            expected_content_hash=expected_content_hash,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    async def upsert_note(
        client: AlexandriaApiClient,
        title: str,
        body: str,
        alexandria_type: str,
        match_by: str,
        note_id: str | None = None,
        path: str | None = None,
        project: str | None = None,
        tags: list[str] | str | None = None,
        status: str | None = None,
        source: str | None = None,
        frontmatter: JSONObject | None = None,
        frontmatter_mode: str = ObsidianFrontmatterMode.MERGE.value,
        expected_content_hash: str | None = None,
        idempotency_key: str | None = None,
    ) -> JSONValue:
        """Create or update by one exact selector, rejecting selector conflicts.

        Args:
            client: Backend HTTP client.
            title: Note title.
            body: Markdown body content.
            alexandria_type: Managed note type.
            match_by: Selector matching mode.
            note_id: Optional stable note identifier.
            path: Optional vault-relative path.
            project: Optional project slug.
            tags: Optional tag list or comma-separated tags.
            status: Optional note lifecycle status.
            source: Optional mutation source label.
            frontmatter: Optional custom frontmatter mapping.
            frontmatter_mode: Frontmatter merge strategy.
            expected_content_hash: Optional expected content hash for CAS validation.
            idempotency_key: Retry-stable identity for the canonical write receipt.

        Returns:
            Backend upserted note response.
        """
        return await _ObsidianGatewayPayloadHelper.write_note(
            client,
            endpoint="/obsidian/notes/upsert",
            title=title,
            body=body,
            alexandria_type=alexandria_type,
            match_by=match_by,
            note_id=note_id,
            path=path,
            project=project,
            tags=tags,
            status=status,
            source=source,
            frontmatter=frontmatter,
            frontmatter_mode=frontmatter_mode,
            expected_content_hash=expected_content_hash,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    async def repair_note_raw(
        client: AlexandriaApiClient,
        path: str,
        expected_content_hash: str,
        raw_content: str,
    ) -> JSONValue:
        """Replace one note's raw source after CAS and parse validation.

        Args:
            client: Backend HTTP client.
            path: Vault-relative Markdown path of the note to repair.
            expected_content_hash: Content hash of the current raw bytes.
            raw_content: Full replacement Markdown source.

        Returns:
            Backend response with the repaired note.
        """
        return await client.post(
            "/obsidian/notes/repair",
            {
                "path": path,
                "expected_content_hash": expected_content_hash,
                "raw_content": raw_content,
            },
        )

    @staticmethod
    async def upsert_report_bundle(
        client: AlexandriaApiClient,
        idempotency_key: str,
        source: JSONObject,
        graph_owners: list[JSONObject],
        reindex: bool = True,
        verify_index_status: bool = True,
        verify_incoming_edges: bool = True,
        verify_duplicates: bool = True,
    ) -> JSONValue:
        """Run one retry-safe Source/owner/reindex/graph verification operation.

        Args:
            client: Backend HTTP client.
            idempotency_key: Retry-stable identity for the report bundle run.
            source: Canonical source note payload.
            graph_owners: Graph owner update payloads.
            reindex: Whether to reindex after writing.
            verify_index_status: Whether to verify index status after writing.
            verify_incoming_edges: Whether to verify incoming graph edges.
            verify_duplicates: Whether to check for duplicate identities.

        Returns:
            Backend report bundle upsert response.
        """
        normalized_source = dict(source)
        frontmatter = normalized_source.get("frontmatter")
        if isinstance(frontmatter, dict):
            normalized_frontmatter = dict(frontmatter)
            normalize_known_frontmatter_metadata(normalized_frontmatter)
            normalized_source["frontmatter"] = normalized_frontmatter
        payload: JSONObject = {
            "idempotency_key": idempotency_key,
            "source": normalized_source,
            "graph_owners": [dict(owner) for owner in graph_owners],
            "reindex": reindex,
            "verify": {
                "index_status": verify_index_status,
                "incoming_edges": verify_incoming_edges,
                "duplicates": verify_duplicates,
            },
        }
        return await client.post("/obsidian/report-bundles/upsert", payload)


class ObsidianNoteBatchGateway:
    """MCP HTTP gateway for vault search and multi-note batch operations."""

    @staticmethod
    async def search_vault(
        client: AlexandriaApiClient,
        query: str,
        limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
        alexandria_type: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> JSONValue:
        """Search Alexandria-managed Obsidian Markdown notes.

        Args:
            client: Backend HTTP client.
            query: Search query.
            limit: Maximum matches.
            alexandria_type: Optional managed note type.
            project: Optional project filter.
            tags: Optional tag filters.

        Returns:
            Backend search response.
        """
        payload: JSONObject = {
            "query": query,
            "limit": bounded_search_limit(limit),
            "tags": items_or_empty(tags),
        }
        if alexandria_type is not None:
            payload["alexandria_type"] = alexandria_type
        if project is not None:
            payload["project"] = project
        response = await client.post("/obsidian/search", payload)
        return compact_vault_search_response(response)

    @staticmethod
    async def batch_read_notes(
        client: AlexandriaApiClient,
        selectors: list[dict[str, str | None]],
    ) -> JSONValue:
        """Read many notes independently by path or note_id.

        Args:
            client: Backend HTTP client.
            selectors: List of note selectors.

        Returns:
            Batch read response from the backend.
        """
        return await client.post(
            "/obsidian/notes/batch-read",
            _ObsidianGatewayPayloadHelper.selector_payloads(selectors),
        )

    @staticmethod
    async def batch_validate_note_links(
        client: AlexandriaApiClient,
        selectors: list[dict[str, str | None]],
    ) -> JSONValue:
        """Validate outgoing links for many notes independently.

        Args:
            client: Backend HTTP client.
            selectors: List of note selectors.

        Returns:
            Batch link validation response from the backend.
        """
        return await client.post(
            "/obsidian/notes/batch-validate-links",
            _ObsidianGatewayPayloadHelper.selector_payloads(selectors),
        )

    @staticmethod
    async def batch_write_notes(
        client: AlexandriaApiClient,
        operations: list[JSONObject],
    ) -> JSONValue:
        """Apply many independent CAS writes with per-item outcomes.

        Args:
            client: Backend HTTP client.
            operations: List of write operations.

        Returns:
            Batch write response from the backend.
        """
        operation_items: list[JSONValue] = [dict(operation) for operation in operations]
        payload: JSONObject = {"operations": operation_items}
        return await client.post("/obsidian/notes/batch-write", payload)


class _ObsidianGatewayPayloadHelper:
    """Shared request payload normalizers for Obsidian note gateway classes."""

    @staticmethod
    async def write_note(
        client: AlexandriaApiClient,
        endpoint: str,
        title: str,
        body: str,
        alexandria_type: str,
        match_by: str,
        note_id: str | None,
        path: str | None,
        project: str | None,
        tags: list[str] | str | None,
        status: str | None,
        source: str | None,
        frontmatter: JSONObject | None,
        frontmatter_mode: str,
        expected_content_hash: str | None = None,
        idempotency_key: str | None = None,
    ) -> JSONValue:
        """Normalize and submit an Obsidian note create, update, or upsert payload.

        Args:
            client: Backend HTTP client.
            endpoint: Backend note mutation endpoint path.
            title: Note title.
            body: Markdown body content.
            alexandria_type: Managed note type.
            match_by: Selector matching mode.
            note_id: Optional stable note identifier.
            path: Optional vault-relative path.
            project: Optional project slug.
            tags: Optional tag list or comma-separated tags.
            status: Optional note lifecycle status.
            source: Optional mutation source label.
            frontmatter: Optional custom frontmatter mapping.
            frontmatter_mode: Frontmatter merge strategy.
            expected_content_hash: Optional expected content hash for CAS validation.
            idempotency_key: Retry-stable identity for the canonical write receipt.

        Returns:
            Backend note write response payload.
        """
        payload: JSONObject = {
            "title": title,
            "body": body,
            "alexandria_type": alexandria_type,
            "match_by": match_by,
            "frontmatter_mode": frontmatter_mode,
        }
        if tags is not None:
            payload["tags"] = normalize_string_collection(tags)
        if status is not None:
            payload["status"] = status
        if source is not None:
            payload["source"] = source
        if frontmatter is not None:
            normalized_frontmatter = dict(frontmatter)
            normalize_known_frontmatter_metadata(normalized_frontmatter)
            payload["frontmatter"] = normalized_frontmatter
        if note_id is not None:
            payload["id"] = note_id
        if path is not None:
            payload["path"] = path
        if project is not None:
            payload["project"] = project
        if expected_content_hash is not None:
            payload["expected_content_hash"] = expected_content_hash
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
        return await client.post(endpoint, payload)

    @staticmethod
    def selector_payloads(selectors: list[dict[str, str | None]]) -> JSONObject:
        """Build a JSON-serializable batch selector request payload.

        Args:
            selectors: Note selector mappings containing note_id or path entries.

        Returns:
            JSONObject containing the normalized selectors list.
        """
        selector_items: list[JSONValue] = [
            dict[str, JSONValue](selector) for selector in selectors
        ]
        return {"selectors": selector_items}
