"""Map canonical note and writer evidence to verified-upsert contracts."""

from __future__ import annotations

from app.obsidian.application.notes.verified_upsert.obsidian_verified_upsert_policy import (
    verified_upsert_frontmatter,
)
from app.obsidian.application.notes.verified_upsert.projection_enums import (
    ProjectionSignal,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedDuplicateSafety,
    ObsidianVerifiedProjectionStatus,
    ObsidianVerifiedUpsertOperation,
    ObsidianVerifiedUpsertRequest,
    ObsidianVerifiedUpsertResult,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianFrontmatterMode,
    ObsidianIndexStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)


class EvidenceMapper:
    """Translate existing source and write observations without upgrading evidence."""

    def note_version(self, note: ObsidianNote) -> int | None:
        """Read the explicit canonical version from note frontmatter."""
        value = note.frontmatter.get("version")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def operation_from_write_result(
        self,
        operation: ObsidianWriteOperation,
    ) -> ObsidianVerifiedUpsertOperation:
        """Map a low-level write observation to the upsert result contract."""
        if operation is ObsidianWriteOperation.CREATED:
            return ObsidianVerifiedUpsertOperation.CREATED
        if operation is ObsidianWriteOperation.UPDATED:
            return ObsidianVerifiedUpsertOperation.UPDATED
        return ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY

    def metadata_status(
        self,
        index_status: ObsidianIndexStatus,
    ) -> ObsidianVerifiedProjectionStatus:
        """Map canonical index evidence into the metadata status."""
        if index_status is ObsidianIndexStatus.INDEXED:
            return ObsidianVerifiedProjectionStatus.VERIFIED
        if index_status is ObsidianIndexStatus.STALE:
            return ObsidianVerifiedProjectionStatus.STALE
        return ObsidianVerifiedProjectionStatus.UNAVAILABLE

    def projection_status(self, value: str) -> ObsidianVerifiedProjectionStatus:
        """Map a low-level projection observation without fabricating readiness."""
        normalized = value.casefold()
        if normalized in {
            ProjectionSignal.INDEXED,
            ProjectionSignal.READY,
            ProjectionSignal.VERIFIED,
            ProjectionSignal.STORED,
        }:
            return ObsidianVerifiedProjectionStatus.VERIFIED
        if normalized == ProjectionSignal.PENDING:
            return ObsidianVerifiedProjectionStatus.PENDING
        if normalized == ProjectionSignal.UNKNOWN:
            return ObsidianVerifiedProjectionStatus.UNKNOWN
        if normalized in {
            ProjectionSignal.STALE,
            ProjectionSignal.REINDEX_REQUIRED,
        }:
            return ObsidianVerifiedProjectionStatus.STALE
        if normalized in {
            ProjectionSignal.UNAVAILABLE,
            ProjectionSignal.FAILED,
            ProjectionSignal.ERROR,
        }:
            return ObsidianVerifiedProjectionStatus.UNAVAILABLE
        return ObsidianVerifiedProjectionStatus.UNKNOWN

    def from_note(
        self,
        request: ObsidianVerifiedUpsertRequest,
        note: ObsidianNote,
        operation: ObsidianVerifiedUpsertOperation,
        warnings: tuple[str, ...] = (),
        write_result_statuses: tuple[str, str, str, str] | None = None,
        readback_verified: bool = True,
        metadata_status: ObsidianVerifiedProjectionStatus | None = None,
        fts_status: ObsidianVerifiedProjectionStatus | None = None,
        graph_edge_index_status: ObsidianVerifiedProjectionStatus | None = None,
        graph_projection_status: ObsidianVerifiedProjectionStatus | None = None,
        storage_status: ObsidianVerifiedProjectionStatus | None = None,
        error_code: str | None = None,
    ) -> ObsidianVerifiedUpsertResult:
        """Map canonical note evidence into the agent-facing result contract."""
        metadata = metadata_status or self.metadata_status(note.index_status)
        if write_result_statuses is None:
            fts = fts_status or (
                ObsidianVerifiedProjectionStatus.VERIFIED
                if metadata is ObsidianVerifiedProjectionStatus.VERIFIED
                else ObsidianVerifiedProjectionStatus.UNKNOWN
            )
            graph_edge = (
                graph_edge_index_status or ObsidianVerifiedProjectionStatus.UNKNOWN
            )
            graph_projection = (
                graph_projection_status or ObsidianVerifiedProjectionStatus.UNKNOWN
            )
        else:
            _, fts_raw, edge_raw, projection_raw = write_result_statuses
            fts = fts_status or self.projection_status(fts_raw)
            graph_edge = graph_edge_index_status or self.projection_status(edge_raw)
            graph_projection = graph_projection_status or self.projection_status(
                projection_raw
            )
        return ObsidianVerifiedUpsertResult(
            operation=operation,
            idempotency_key=request.idempotency_key,
            logical_identity=request.identity,
            note_id=note.note_id,
            canonical_path=note.relative_path,
            content_hash=note.content_hash,
            version=self.note_version(note),
            storage_status=(
                storage_status or ObsidianVerifiedProjectionStatus.VERIFIED
            ),
            readback_verified=readback_verified,
            metadata_status=metadata,
            fts_status=fts,
            vector_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
            graph_edge_index_status=graph_edge,
            graph_projection_status=graph_projection,
            duplicate_safety=ObsidianVerifiedDuplicateSafety.VERIFIED,
            warnings=warnings,
            error_code=error_code,
        )


def build_write_command(
    request: ObsidianVerifiedUpsertRequest,
    canonical_path: str,
    existing: ObsidianNote | None,
) -> ObsidianWriteNote:
    """Build a canonical write without accepting caller-owned identity fields."""
    frontmatter = verified_upsert_frontmatter(request)
    payload = ObsidianSaveNote(
        title=request.title,
        body=request.body,
        alexandria_type=request.alexandria_type,
        note_id=None if existing is None else existing.note_id,
        relative_path=canonical_path,
        tags=request.tags,
        status="active",
        project=request.identity.project,
        source=request.source,
        frontmatter=frontmatter,
        expected_content_hash=request.expected_content_hash,
    )
    return ObsidianWriteNote(
        note=payload,
        write_mode=ObsidianWriteMode.UPSERT,
        match_by=ObsidianWriteMatchBy.PATH,
        frontmatter_mode=ObsidianFrontmatterMode.MERGE,
    )
