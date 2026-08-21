"""Context record lifecycle and access-audit mutations."""

from __future__ import annotations

from app.memory.application.contexts.records.context_record_query_service import (
    owns_canonical_context,
)
from app.memory.domain.contracts.context_contracts import ContextAccessCreate
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.context_enums import (
    ContextAccessActorType,
    ContextAccessMethod,
)
from app.memory.domain.repositories.contexts.canonical_context_repository import (
    ICanonicalContextRepository,
)
from app.memory.domain.repositories.contexts.context_record_mutation_repository import (
    IContextRecordMutationRepository,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.types.types_convert_utils import enum_value, now_utc


class ContextRecordLifecycleService:
    """Mutate Context lifecycle and SQL access audit state by storage ownership."""

    def __init__(
        self,
        repository: IContextRecordMutationRepository,
        canonical_repository: ICanonicalContextRepository | None,
    ) -> None:
        """Create the Context record lifecycle service.

        Args:
            repository: SQL-backed Context repository.
            canonical_repository: Optional canonical Markdown Context repository.
        """
        self._repository = repository
        self._canonical_repository = canonical_repository

    async def archive(self, context_id: str) -> ContextRecord:
        """Archive one Context through its owning storage surface.

        Args:
            context_id: Context identifier.

        Returns:
            Archived Context read model.
        """
        canonical_repository = self._canonical_repository
        if owns_canonical_context(canonical_repository, context_id):
            assert canonical_repository is not None
            return await canonical_repository.archive(context_id)
        return await self._repository.archive(context_id)

    async def supersede(
        self,
        context_id: str,
        replacement_context_id: str,
    ) -> tuple[ContextRecord, ContextRecord]:
        """Link one canonical Context to an existing canonical replacement.

        Args:
            context_id: Source-qualified Context identifier to supersede.
            replacement_context_id: Source-qualified replacement Context identifier.

        Returns:
            Superseded and replacement canonical Context read models.
        """
        canonical_repository = self._canonical_repository
        if not owns_canonical_context(
            canonical_repository, context_id
        ) or not owns_canonical_context(canonical_repository, replacement_context_id):
            raise MemoryContextValidationError(
                "Supersede requires source-qualified canonical Context identifiers"
            )
        if context_id == replacement_context_id:
            raise MemoryContextValidationError(
                "INVALID_SUPERSEDE: Context cannot supersede itself"
            )
        assert canonical_repository is not None
        return await canonical_repository.supersede(
            context_id,
            replacement_context_id,
        )

    async def delete(self, context_id: str) -> None:
        """Hard-delete one SQL-backed Context.

        Args:
            context_id: Context identifier.
        """
        if owns_canonical_context(self._canonical_repository, context_id):
            raise MemoryContextValidationError(
                "Canonical Markdown contexts cannot be hard-deleted through SQL"
            )
        await self._repository.delete(context_id)

    async def record_access(
        self,
        context_id: str,
        actor_name: str = "Alexandria UI",
        actor_type: ContextAccessActorType = ContextAccessActorType.UI,
        access_method: ContextAccessMethod = ContextAccessMethod.DETAIL_VIEW,
        source_surface: str | None = "context-detail",
    ) -> ContextRecord:
        """Record one SQL-backed Context access event.

        Args:
            context_id: Context identifier.
            actor_name: Actor label to store with the access event.
            actor_type: Actor category.
            access_method: Access method category.
            source_surface: Optional UI or tool surface that caused access.

        Returns:
            Updated Context read model.
        """
        if owns_canonical_context(self._canonical_repository, context_id):
            raise MemoryContextValidationError(
                "Canonical Markdown context access events are not stored in SQL"
            )
        actor_type = enum_value(actor_type, ContextAccessActorType, "actor_type")
        access_method = enum_value(
            access_method,
            ContextAccessMethod,
            "access_method",
        )
        return await self._repository.record_access(
            ContextAccessCreate(
                context_id=context_id,
                accessed_at=now_utc(),
                actor_name=actor_name,
                actor_type=actor_type,
                access_method=access_method,
                source_surface=source_surface,
            )
        )
