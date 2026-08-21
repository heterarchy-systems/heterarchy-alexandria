"""Application bridge from Context APIs to canonical Obsidian operations."""

from __future__ import annotations

from app.memory.application.integration.obsidian_context_read_mapper import (
    OBSIDIAN_CONTEXT_ID_PREFIX,
    context_record_from_obsidian_note,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.repositories.contexts.canonical_context_repository import (
    ICanonicalContextRepository,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


class ObsidianCanonicalContextGateway(ICanonicalContextRepository):
    """Expose source-qualified Obsidian Context lifecycle operations."""

    def __init__(self, service: ObsidianService) -> None:
        self._service = service

    def owns(self, context_id: str) -> bool:
        """Return whether the identifier selects the Obsidian canonical source.

        Args:
            context_id: Source-qualified Context identifier.

        Returns:
            True when the identifier belongs to this gateway.
        """
        return context_id.startswith(OBSIDIAN_CONTEXT_ID_PREFIX)

    async def get(self, context_id: str) -> ContextRecord | None:
        """Return an indexed canonical Context when this gateway owns the ID.

        Args:
            context_id: Source-qualified Context identifier.

        Returns:
            Canonical Context, or None when absent or not indexed.
        """
        note_id = _obsidian_note_id(context_id)
        if note_id is None:
            return None
        try:
            note = await self._service.read_note(note_id)
        except ObsidianNotFoundError:
            return None
        if (
            note.alexandria_type is not AlexandriaNoteType.CONTEXT
            or note.index_status is not ObsidianIndexStatus.INDEXED
        ):
            return None
        return context_record_from_obsidian_note(note)

    async def archive(self, context_id: str) -> ContextRecord:
        """Archive an owned Context by patching its canonical Markdown.

        Args:
            context_id: Source-qualified Context identifier.

        Returns:
            Archived canonical Context.
        """
        note_id = _obsidian_note_id(context_id)
        if note_id is None:
            raise MemoryContextNotFoundError(f"Context not found: {context_id}")
        try:
            note = await self._service.archive_context(note_id)
        except ObsidianNotFoundError as exc:
            raise MemoryContextNotFoundError(
                f"Context not found: {context_id}"
            ) from exc
        except ObsidianValidationError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        return context_record_from_obsidian_note(note)

    async def supersede(
        self,
        context_id: str,
        replacement_context_id: str,
    ) -> tuple[ContextRecord, ContextRecord]:
        """Link two owned canonical Context records.

        Args:
            context_id: Source-qualified Context identifier to supersede.
            replacement_context_id: Source-qualified replacement Context identifier.

        Returns:
            Superseded and replacement canonical Context read models.
        """
        note_id = _obsidian_note_id(context_id)
        replacement_note_id = _obsidian_note_id(replacement_context_id)
        if note_id is None or replacement_note_id is None:
            raise MemoryContextValidationError(
                "Supersede requires source-qualified Obsidian Context identifiers"
            )
        try:
            superseded, replacement = await self._service.supersede_context(
                note_id,
                replacement_note_id,
            )
        except ObsidianNotFoundError as exc:
            raise MemoryContextNotFoundError(
                "Superseded or replacement Context was not found"
            ) from exc
        except ObsidianValidationError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        return (
            context_record_from_obsidian_note(superseded),
            context_record_from_obsidian_note(replacement),
        )


def _obsidian_note_id(context_id: str) -> str | None:
    if not context_id.startswith(OBSIDIAN_CONTEXT_ID_PREFIX):
        return None
    note_id = context_id.removeprefix(OBSIDIAN_CONTEXT_ID_PREFIX).strip()
    return note_id or None
