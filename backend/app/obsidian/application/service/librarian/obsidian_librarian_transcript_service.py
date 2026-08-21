"""Durable transcript persistence for librarian conversations."""

from __future__ import annotations

from app.obsidian.application.notes.obsidian_note_templates import (
    LIBRARIAN_OPERATIONS_FOLDER,
    librarian_transcript_body,
)
from app.obsidian.application.service.librarian.obsidian_librarian_conversation_contracts import (
    ObsidianConversationSaveHook,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianAsk,
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianSearchHit,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.types.extra_types import JSONObject


class ObsidianLibrarianTranscriptService:
    """Persist one librarian conversation through the canonical note save path."""

    def __init__(
        self,
        vault_config_store: ObsidianVaultConfigStore,
        save_note: ObsidianConversationSaveHook,
    ) -> None:
        """Initialize transcript persistence dependencies.

        Args:
            vault_config_store: Current vault and Alexandria root settings.
            save_note: Canonical note save hook.
        """
        self._vault_config_store = vault_config_store
        self._save_note = save_note

    async def save(
        self,
        payload: ObsidianLibrarianAsk,
        answer: str,
        hits: list[ObsidianSearchHit],
        response: JSONObject,
    ) -> ObsidianNote:
        conversation_id = str(response["conversation_id"])
        body = librarian_transcript_body(payload, answer, hits)
        return await self._save_note(
            ObsidianSaveNote(
                title=f"Librarian Chat {conversation_id}",
                body=body,
                alexandria_type=AlexandriaNoteType.LIBRARIAN_CHAT,
                note_id=conversation_id,
                relative_path=(
                    f"{self._vault_config_store.current().alexandria_root}/{LIBRARIAN_OPERATIONS_FOLDER}/"
                    f"Chats/{conversation_id}.md"
                ),
                tags=("librarian", "obsidian-chat"),
                project=payload.project,
                source="obsidian-plugin",
                frontmatter={
                    "conversation_id": conversation_id,
                    "active_note_path": payload.active_note_path,
                    "linked_note_ids": [hit.note.note_id for hit in hits],
                    "source_refs": [
                        {
                            "id": hit.note.note_id,
                            "path": hit.note.relative_path,
                            "relation": "cites",
                        }
                        for hit in hits
                    ],
                },
            )
        )
