"""Stable error mapping and persistence for vault indexing diagnostics."""

from __future__ import annotations

from app.obsidian.domain.entities.obsidian_note import ObsidianIndexError
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianValidationError,
)
from app.shared.types.types_convert_utils import now_utc


class VaultIndexDiagnostics:
    """Persist and collect the stable diagnostics produced by a vault reindex."""

    def __init__(self, repository: IObsidianIndexRepository) -> None:
        """Bind the canonical index repository for diagnostic writes.

        Args:
            repository: Repository owning persisted index errors.
        """
        self._repository = repository

    async def record(
        self,
        relative_path: str,
        context_id: str | None,
        error: OSError | ValueError | ObsidianIndexWriteError | ObsidianValidationError,
        errors: list[str],
        details: list[ObsidianIndexError],
    ) -> None:
        """Persist and append one structured per-note reindex failure.

        Args:
            relative_path: Relative path used by this operation.
            context_id: Identifier for context.
            error: Error value being processed.
            errors: Mutable run-local error messages.
            details: Mutable run-local structured errors.
        """
        error_code = index_error_code(error)
        safe_message = _safe_index_error_message(error_code)
        detail = ObsidianIndexError(
            note_path=relative_path,
            context_id=context_id,
            error_code=error_code,
            error_message=safe_message,
            detected_at=now_utc(),
        )
        await self._repository.record_index_error(detail)
        details.append(detail)
        errors.append(f"{relative_path}: {detail.error_code.value}: {safe_message}")


def index_error_code(
    error: OSError | ValueError | ObsidianIndexWriteError | ObsidianValidationError,
) -> ObsidianIndexErrorCode:
    """Map one indexing failure to its stable error code.

    Args:
        error: Indexing or validation failure.

    Returns:
        Stable public error code.
    """
    message = str(error)
    message_prefix = message.partition(":")[0]
    try:
        return ObsidianIndexErrorCode(message_prefix)
    except ValueError:
        for error_code in ObsidianIndexErrorCode:
            if error_code.value in message:
                return error_code
        if isinstance(error, OSError):
            return ObsidianIndexErrorCode.SOURCE_READ_FAILED
        if isinstance(error, ObsidianIndexWriteError):
            return ObsidianIndexErrorCode.INDEX_WRITE_FAILED
        return ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR


def _safe_index_error_message(error_code: ObsidianIndexErrorCode) -> str:
    """Map an indexing error code to its stable, secret-safe message.

    Args:
        error_code: Error code used by this operation.

    Returns:
        Stable message for the error code.
    """
    if error_code is ObsidianIndexErrorCode.INDEX_WRITE_FAILED:
        return "Rebuildable index write failed"
    if error_code is ObsidianIndexErrorCode.SOURCE_READ_FAILED:
        return "Canonical Markdown source could not be read"
    if error_code is ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED:
        return "Frontmatter contains a secret-like field"
    if error_code is ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION:
        return "Managed note path failed security validation"
    if error_code in (
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_ID,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_CONTENT,
    ):
        return "Context identity conflicts with another managed note"
    if error_code is ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR:
        return "Markdown frontmatter could not be validated"
    return "Context frontmatter failed validation"
