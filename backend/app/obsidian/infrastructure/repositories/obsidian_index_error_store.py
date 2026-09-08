"""Structured Obsidian index failure persistence store."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexErrorCode,
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_index_row_cleanup import (
    discard_obsidian_note_index,
    get_obsidian_file_by_path,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.types.types_convert_utils import aware_utc_datetime


class ObsidianIndexErrorStore:
    """Record and read structured note indexing failures."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the error store.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def record_index_error(self, error: ObsidianIndexError) -> None:
        """Persist a failed note row so operators can observe and recover it.

        Args:
            error: Structured note indexing failure.
        """
        path_model = await get_obsidian_file_by_path(self._session, error.note_path)
        note_id = f"index-error:{hash_text(error.note_path)[:32]}"
        model = await self._session.get(ObsidianFileORM, note_id)
        if path_model is not None and path_model.note_id != note_id:
            await discard_obsidian_note_index(self._session, path_model.note_id)
            await self._session.delete(path_model)
            await self._session.flush()
        if model is None:
            model = ObsidianFileORM(note_id=note_id)
            self._session.add(model)
        model.relative_path = error.note_path
        model.alexandria_type = "context"
        model.title = error.note_path.rsplit("/", maxsplit=1)[-1].removesuffix(".md")
        model.status = "error"
        model.tags = []
        model.project = None
        model.source = "reindex"
        model.content_hash = hash_text(error.note_path)
        model.frontmatter_json = {"index_error_code": error.error_code.value}
        if error.context_id is not None:
            model.frontmatter_json["id"] = error.context_id
        model.body = ""
        model.index_status = ObsidianIndexStatus.ERROR.value
        model.error_message = error.error_message
        model.size_bytes = 0
        model.modified_at = error.detected_at
        model.indexed_at = error.detected_at
        await self._session.flush()

    async def clear_index_error(self, note_path: str) -> None:
        """Remove a resolved failed-note row without touching indexed content.

        Args:
            note_path: Vault-relative Markdown path whose source is readable again.
        """
        model = await get_obsidian_file_by_path(self._session, note_path)
        if model is None or model.index_status != ObsidianIndexStatus.ERROR.value:
            return
        await discard_obsidian_note_index(self._session, model.note_id)
        await self._session.delete(model)
        await self._session.flush()

    async def list_index_errors(
        self,
        limit: int = 20,
    ) -> list[ObsidianIndexError]:
        """Return recent failed-note rows as structured diagnostics.

        Args:
            limit: Maximum number of recent errors to return.

        Returns:
            Recent structured indexing failures.
        """
        rows = await self._session.scalars(
            select(ObsidianFileORM)
            .where(ObsidianFileORM.index_status == ObsidianIndexStatus.ERROR.value)
            .order_by(ObsidianFileORM.indexed_at.desc())
            .limit(limit)
        )
        return [_index_error_from_model(model) for model in rows.all()]


def _index_error_from_model(model: ObsidianFileORM) -> ObsidianIndexError:
    """Execute index error from model.

    Args:
        model: Model used by this operation.

    Returns:
        ObsidianIndexError result produced by index error from model.
    """
    error_text = model.error_message or "Unknown index error"
    stored_error_code = model.frontmatter_json.get("index_error_code")
    if isinstance(stored_error_code, str):
        try:
            error_code = ObsidianIndexErrorCode(stored_error_code)
        except ValueError:
            error_code = ObsidianIndexErrorCode.INDEX_WRITE_FAILED
        error_message = error_text
    else:
        legacy_code, separator, legacy_message = error_text.partition(":")
        try:
            error_code = ObsidianIndexErrorCode(legacy_code)
        except ValueError:
            error_code = ObsidianIndexErrorCode.INDEX_WRITE_FAILED
        error_message = legacy_message if separator else error_text
    stored_context_id = model.frontmatter_json.get("id")
    if isinstance(stored_context_id, str):
        context_id = stored_context_id
    elif model.note_id.startswith("index-error:"):
        context_id = None
    else:
        context_id = model.note_id
    return ObsidianIndexError(
        note_path=model.relative_path,
        context_id=context_id,
        error_code=error_code,
        error_message=error_message.strip(),
        detected_at=aware_utc_datetime(model.indexed_at),
    )
