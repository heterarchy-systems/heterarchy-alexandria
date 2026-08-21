"""Source reference entities for librarian knowledge packets."""

from __future__ import annotations

from dataclasses import dataclass

from app.librarian.domain.event_enum.source_ref_enums import SourceRefType
from app.librarian.domain.types.librarian_brief_payload_types import SourceRefPayload
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRef:
    """Reference to evidence that can be fetched only when selected.

    Args:
        source_type: Referenced artifact type.
        source_id: Stable source identifier.
        title: Human-readable title.
        detail_path: Backend path for selected full-load.
        preview: Optional bounded preview text.
    """

    source_type: SourceRefType
    source_id: str
    title: str
    detail_path: str
    preview: str | None = None

    def __post_init__(self) -> None:
        """Validate source reference invariants."""
        try:
            normalized_source_type = SourceRefType(self.source_type)
        except (TypeError, ValueError) as exc:
            raise LibrarianValidationError("source_type is invalid") from exc
        object.__setattr__(self, "source_type", normalized_source_type)
        if not self.source_id.strip():
            raise LibrarianValidationError("source_id is required")
        if not self.title.strip():
            raise LibrarianValidationError("title is required")
        if not self.detail_path.strip():
            raise LibrarianValidationError("detail_path is required")

    def to_payload(self) -> SourceRefPayload:
        """Return a public TypedDict payload.

        Returns:
            SourceRefPayload: JSON-ready source reference payload.
        """
        return SourceRefPayload(
            source_type=self.source_type,
            source_id=self.source_id,
            title=self.title,
            detail_path=self.detail_path,
            preview=self.preview,
        )
