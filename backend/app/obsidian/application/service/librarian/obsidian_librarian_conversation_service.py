"""Obsidian-grounded librarian conversation application service."""

from __future__ import annotations

from app.obsidian.application.graph.obsidian_graph_writeback import (
    graph_link_save_payload,
)
from app.obsidian.application.librarian.delegation.obsidian_librarian_delegation import (
    ObsidianLibrarianDelegateService,
    apply_provider_delegate,
)
from app.obsidian.application.notes.obsidian_note_templates import (
    conversation_id,
    librarian_answer,
    source_refs_for_librarian,
)
from app.obsidian.application.service.librarian.obsidian_librarian_conversation_contracts import (
    ObsidianConversationReadHook,
    ObsidianConversationSaveHook,
    ObsidianConversationSearchHook,
)
from app.obsidian.application.service.librarian.obsidian_librarian_conversation_policy import (
    _delegate_status,
    _librarian_input_context,
    _selection_excerpt,
)
from app.obsidian.application.service.librarian.obsidian_librarian_source_service import (
    ObsidianLibrarianSourceService,
)
from app.obsidian.application.service.librarian.obsidian_librarian_transcript_service import (
    ObsidianLibrarianTranscriptService,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianAsk,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianValidationError,
)
from app.shared.types.extra_types import JSONObject

__all__ = (
    "ObsidianConversationReadHook",
    "ObsidianConversationSaveHook",
    "ObsidianConversationSearchHook",
    "ObsidianLibrarianConversationService",
)


class ObsidianLibrarianConversationService:
    """Answer librarian questions and persist approved conversation artifacts."""

    def __init__(
        self,
        vault_config_store: ObsidianVaultConfigStore,
        delegate_service: ObsidianLibrarianDelegateService | None,
        read_note_by_path: ObsidianConversationReadHook,
        save_note: ObsidianConversationSaveHook,
        search: ObsidianConversationSearchHook,
    ) -> None:
        """Create the conversation service."""
        self._delegate_service = delegate_service
        self._read_note_by_path = read_note_by_path
        self._save_note = save_note
        self._source_service = ObsidianLibrarianSourceService(
            read_note_by_path=read_note_by_path,
            search=search,
        )
        self._transcript_service = ObsidianLibrarianTranscriptService(
            vault_config_store=vault_config_store,
            save_note=save_note,
        )

    async def apply_graph_links(
        self,
        active_note_path: str,
        response: JSONObject,
    ) -> ObsidianNote:
        """Apply approved librarian source refs to an active note and reindex it.

        Args:
            active_note_path: Vault-relative path of the note approved for mutation.
            response: Librarian answer payload containing source refs.

        Returns:
            Updated active note loaded from the rebuilt index.
        """
        note = await self._read_note_by_path(active_note_path)
        return await self._save_note(
            graph_link_save_payload(note=note, response=response)
        )

    async def ask(self, payload: ObsidianLibrarianAsk) -> JSONObject:
        """Return an Obsidian-grounded librarian answer payload.

        Args:
            payload: Librarian question and optional active-note context.

        Returns:
            JSON-compatible answer payload with source references.
        """
        if not payload.query.strip():
            raise ObsidianValidationError("query is required")
        active_note = await self._source_service.active_note(payload.active_note_path)
        selection_excerpt = _selection_excerpt(payload.selection)
        hits = await self._source_service.source_hits(payload)
        answer = librarian_answer(payload, hits, active_note)
        source_refs = source_refs_for_librarian(hits, active_note)
        input_context = _librarian_input_context(
            payload=payload,
            active_note=active_note,
            selection_excerpt=selection_excerpt,
            source_refs=source_refs,
        )
        response: JSONObject = {
            "answer_markdown": answer,
            "source_refs": source_refs,
            "input_context": input_context,
            "context_status": str(input_context["status"]),
            "action_preview": [
                "save_chat",
                "create_context_note",
                "create_skill_draft",
            ],
            "conversation_id": conversation_id(),
            "transcript_path": None,
            "delegate_status": _delegate_status(payload),
            "provider_id": payload.provider_id,
            "profile_id": payload.profile_id,
        }
        await apply_provider_delegate(
            payload=payload,
            response=response,
            delegate_service=self._delegate_service,
        )
        if payload.save_transcript:
            transcript = await self._transcript_service.save(
                payload, str(response["answer_markdown"]), hits, response
            )
            response["transcript_path"] = transcript.relative_path
        return response
