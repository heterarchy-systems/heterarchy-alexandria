"""Build Obsidian note index payloads from Markdown files."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from app.obsidian.application.graph.relations.native_obsidian_graph_edge_builder import (
    create_native_obsidian_graph_edge_builder,
)
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
    normalized_context_frontmatter,
)
from app.obsidian.application.notes.frontmatter.obsidian_frontmatter_redaction import (
    frontmatter_contains_secret_field,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.domain.obsidian_note_type_aliases import (
    normalized_alexandria_note_type,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    FrontmatterValue,
    frontmatter_json,
    frontmatter_list,
    frontmatter_text,
)
from app.obsidian.infrastructure.markdown.native_note_index_compute import (
    create_native_note_index_compute_provider,
)


def note_index_from_path(
    path: Path,
    relative_path: str,
    alexandria_root: str,
    max_source_bytes: int | None = None,
) -> ObsidianNoteIndex | None:
    """Read one Markdown file and build an index payload when managed.

    Args:
        path: Absolute Markdown path.
        relative_path: Vault-relative Markdown path.
        alexandria_root: Managed Alexandria root, or "." when the vault is root.
        max_source_bytes: Optional source-byte ceiling for bounded reads.

    Returns:
        Index payload, or None when Alexandria frontmatter is missing.
    """
    text = _read_source_text(path, max_source_bytes=max_source_bytes)
    if frontmatter_contains_secret_field(text):
        raise ValueError(
            "FRONTMATTER_SECRET_DETECTED: frontmatter contains a secret-like field"
        )
    computed = create_native_note_index_compute_provider().compute(text, relative_path)
    note_type = _note_type_from_frontmatter(computed.frontmatter)
    note_id = frontmatter_text(computed.frontmatter, "id")
    if note_type is None:
        return None
    if not note_id:
        raise ValueError("FRONTMATTER_PARSE_ERROR: managed note is missing id")
    stat = path.stat()
    body = computed.body
    frontmatter = frontmatter_json(computed.frontmatter)
    frontmatter["alexandria_type"] = note_type.value
    project = frontmatter_text(computed.frontmatter, "project")
    status = frontmatter_text(computed.frontmatter, "status") or "active"
    note_content_hash = computed.content_hash
    if note_type is AlexandriaNoteType.CONTEXT:
        identity = context_identity_from_frontmatter(
            frontmatter,
            project=project,
            status=status,
            generated_content_hash=context_content_hash(body),
        )
        frontmatter.update(normalized_context_frontmatter(identity))
        frontmatter.pop("provenance", None)
        project = identity.project
        status = identity.status.value
        note_content_hash = identity.content_hash
    return ObsidianNoteIndex(
        note_id=note_id,
        relative_path=relative_path,
        alexandria_type=note_type,
        title=computed.title,
        status=status,
        tags=tuple(frontmatter_list(computed.frontmatter, "tags")),
        project=project,
        source=frontmatter_text(computed.frontmatter, "source"),
        content_hash=note_content_hash,
        frontmatter=frontmatter,
        body=body,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        chunks=computed.chunks,
        edges=tuple(
            create_native_obsidian_graph_edge_builder().build(
                note_id=note_id,
                relative_path=relative_path,
                alexandria_root=alexandria_root,
                frontmatter=frontmatter,
                body=body,
            )
        ),
    )


def _read_source_text(path: Path, max_source_bytes: int | None) -> str:
    """Read complete UTF-8 source text with an optional byte ceiling."""
    if max_source_bytes is None:
        return path.read_text(encoding="utf-8")
    if max_source_bytes <= 0:
        raise ValueError("SOURCE_SCAN_LIMIT_EXCEEDED")
    with path.open("rb") as source:
        content = source.read(max_source_bytes + 1)
    if len(content) > max_source_bytes:
        raise ValueError("SOURCE_SCAN_LIMIT_EXCEEDED")
    return content.decode("utf-8")


def _note_type_from_frontmatter(
    frontmatter: Mapping[str, FrontmatterValue],
) -> AlexandriaNoteType | None:
    """Execute note type from frontmatter.

    Args:
        frontmatter: Frontmatter used by this operation.

    Returns:
        AlexandriaNoteType | None result produced by note type from frontmatter.
    """
    explicit_value = frontmatter_text(frontmatter, "alexandria_type")
    if explicit_value:
        note_type = normalized_alexandria_note_type(explicit_value)
        if note_type is None:
            raise ValueError("FRONTMATTER_PARSE_ERROR: invalid alexandria_type")
        return note_type
    for key in ("type", "item_type"):
        note_type = normalized_alexandria_note_type(frontmatter_text(frontmatter, key))
        if note_type is not None:
            return note_type
    return None
