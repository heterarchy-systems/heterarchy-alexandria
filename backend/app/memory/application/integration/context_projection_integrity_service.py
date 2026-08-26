"""Full-index Obsidian-to-Context projection integrity validation."""

from __future__ import annotations

import re
from datetime import timedelta

from app.memory.application.integration.context_projection_integrity_ports import (
    ContextProjectionIntegritySourcePort,
)
from app.memory.application.integration.obsidian_context_read_mapper import (
    context_record_from_obsidian_note,
)
from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegrityFailure,
    ContextProjectionIntegritySnapshot,
)
from app.memory.domain.repositories.projection_integrity.context_projection_integrity_repository import (
    IContextProjectionIntegrityRepository,
)
from app.shared.types.types_convert_utils import now_utc

_FAILURE_CODE = re.compile(r"^([A-Z][A-Z0-9_]+):")


class ContextProjectionIntegrityService:
    """Validate all indexed managed notes through the production Context mapper."""

    def __init__(
        self,
        source: ContextProjectionIntegritySourcePort,
        repository: IContextProjectionIntegrityRepository,
        max_age_seconds: int,
    ) -> None:
        """Create the projection integrity service.

        Args:
            source: Rebuildable indexed-note read boundary.
            repository: Latest projection-integrity snapshot persistence boundary.
            max_age_seconds: Maximum accepted age of the latest complete scan.
        """
        if max_age_seconds <= 0:
            raise ValueError(
                "PROJECTION_INTEGRITY_MAX_AGE_INVALID: max age must be positive"
            )
        self._source = source
        self._repository = repository
        self._max_age = timedelta(seconds=max_age_seconds)

    async def refresh(self) -> ContextProjectionIntegritySnapshot:
        """Run one full indexed-note projection scan and persist its result.

        Returns:
            Persisted projection-integrity snapshot for the scanned source revision.
        """
        notes = await self._source.list_indexed_notes()
        source_revision = await self._source.projection_source_revision()
        failure_counts: dict[str, int] = {}
        valid_count = 0
        for note in notes:
            try:
                context_record_from_obsidian_note(note)
            except (KeyError, TypeError, ValueError) as exc:
                code = _projection_failure_code(exc)
                failure_counts[code] = failure_counts.get(code, 0) + 1
            else:
                valid_count += 1
        failures = tuple(
            ContextProjectionIntegrityFailure(code=code, count=count)
            for code, count in sorted(failure_counts.items())
        )
        snapshot = ContextProjectionIntegritySnapshot(
            checked=True,
            available=True,
            source_revision=source_revision,
            current_source_revision=source_revision,
            scanned_count=len(notes),
            valid_count=valid_count,
            invalid_count=len(notes) - valid_count,
            failures=failures,
            checked_at=now_utc(),
            stale=False,
        )
        await self._repository.replace_latest(snapshot)
        return snapshot

    async def snapshot(self) -> ContextProjectionIntegritySnapshot:
        """Return persisted projection integrity with current source freshness.

        Returns:
            Latest snapshot annotated with current revision and staleness evidence.
        """
        current_source_revision = await self._source.projection_source_revision()
        persisted = await self._repository.get_latest()
        if persisted is None:
            return ContextProjectionIntegritySnapshot(
                checked=True,
                available=False,
                source_revision=None,
                current_source_revision=current_source_revision,
                scanned_count=0,
                valid_count=0,
                invalid_count=0,
                failures=(),
                checked_at=None,
                stale=True,
            )
        checked_at = persisted.checked_at
        age_stale = checked_at is None or now_utc() - checked_at > self._max_age
        revision_stale = persisted.source_revision != current_source_revision
        return ContextProjectionIntegritySnapshot(
            checked=True,
            available=True,
            source_revision=persisted.source_revision,
            current_source_revision=current_source_revision,
            scanned_count=persisted.scanned_count,
            valid_count=persisted.valid_count,
            invalid_count=persisted.invalid_count,
            failures=persisted.failures,
            checked_at=checked_at,
            stale=age_stale or revision_stale,
        )


def _projection_failure_code(error: BaseException) -> str:
    """Return a bounded machine-readable projection failure code.

    Args:
        error: Projection exception raised by the production mapper.

    Returns:
        Stable aggregate code suitable for operational diagnostics.
    """
    match = _FAILURE_CODE.match(str(error))
    if match is not None:
        return match.group(1)
    if isinstance(error, KeyError):
        return "PROJECTION_KEY_ERROR"
    if isinstance(error, TypeError):
        return "PROJECTION_TYPE_ERROR"
    return "PROJECTION_VALIDATION_ERROR"
