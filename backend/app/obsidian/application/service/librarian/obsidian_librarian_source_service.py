"""Active-note and indexed-evidence retrieval for librarian conversations."""

from __future__ import annotations

from app.obsidian.application.librarian.obsidian_librarian_ranking import (
    fuse_librarian_search_hits,
)
from app.obsidian.application.librarian.obsidian_librarian_retrieval import (
    librarian_excluded_types,
    librarian_query_text,
    librarian_query_variants,
    librarian_search_limit,
    librarian_type_filters,
)
from app.obsidian.application.service.librarian.obsidian_librarian_conversation_contracts import (
    ObsidianConversationReadHook,
    ObsidianConversationSearchHook,
)
from app.obsidian.application.service.librarian.obsidian_librarian_conversation_policy import (
    _librarian_search_queries,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianLibrarianAsk
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianSearchHit,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


class ObsidianLibrarianSourceService:
    """Load active-note context and deduplicated indexed evidence."""

    def __init__(
        self,
        read_note_by_path: ObsidianConversationReadHook,
        search: ObsidianConversationSearchHook,
    ) -> None:
        """Initialize source retrieval boundaries.

        Args:
            read_note_by_path: Canonical note read hook.
            search: Indexed Obsidian search hook.
        """
        self._read_note_by_path = read_note_by_path
        self._search = search

    async def active_note(self, relative_path: str | None) -> ObsidianNote | None:
        """Resolve the active librarian source note.

        Args:
            relative_path: Vault-relative path of the active note.

        Returns:
            Active Obsidian note, or None when no active note is available.
        """
        if not relative_path:
            return None
        try:
            return await self._read_note_by_path(relative_path)
        except ObsidianNotFoundError as exc:
            raise ObsidianValidationError(
                f"active_note_read_failed: {relative_path}"
            ) from exc

    async def source_hits(
        self, payload: ObsidianLibrarianAsk
    ) -> list[ObsidianSearchHit]:
        """Resolve librarian source search hits.

        Args:
            payload: Validated request or librarian payload consumed by the operation.

        Returns:
            Obsidian search hits selected as librarian sources.
        """
        query_text = librarian_query_text(payload)
        search_limit = librarian_search_limit(payload.max_source_refs)
        preferred_types = librarian_type_filters(payload.preferred_alexandria_types)
        excluded_types = librarian_excluded_types(preferred_types)
        ranked_hit_lists: list[list[ObsidianSearchHit]] = []
        for query_variant in librarian_query_variants(query_text):
            search_queries = _librarian_search_queries(
                query=query_variant,
                limit=search_limit,
                project=payload.project,
                preferred_types=preferred_types,
                excluded_types=excluded_types,
            )
            ranked_hit_lists.extend(
                [await self._search(search_query) for search_query in search_queries]
            )
        return fuse_librarian_search_hits(
            ranked_hit_lists=ranked_hit_lists,
            limit=payload.max_source_refs,
        )
