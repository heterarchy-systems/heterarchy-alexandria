"""Real-extension parity for Python adapters over native document/chunk compute."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import sysconfig
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import anyio

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (  # noqa: E402
    ReconciliationCandidateComputeItem,
    ReconciliationCandidateComputePolicy,
)
from app.memory.infrastructure.providers.native_memory_reconciliation_candidate_compute_provider import (  # noqa: E402
    create_native_memory_reconciliation_candidate_compute_provider,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (  # noqa: E402
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.application.graph.relations.native_obsidian_graph_edge_builder import (  # noqa: E402
    create_native_obsidian_graph_edge_builder,
)
from app.obsidian.application.notes import (  # noqa: E402
    obsidian_note_indexer as note_indexer_module,
)
from app.obsidian.domain.entities.obsidian_note import (  # noqa: E402
    ObsidianEdge,
    ObsidianNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (  # noqa: E402
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianIndexStatus,
    ObsidianRelationType,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (  # noqa: E402
    create_native_obsidian_graph_projection_compute_provider,
)
from app.obsidian.infrastructure.markdown.native_frontmatter import (  # noqa: E402
    create_native_markdown_document_parser,
)
from app.obsidian.infrastructure.markdown.native_note_index_compute import (  # noqa: E402
    create_native_note_index_compute_provider,
)
from app.shared.compute.native_text_hashing import (  # noqa: E402
    TextHashInput,
    create_native_text_hash_batcher,
)
from app.shared.search.native_markdown_text_chunking import (  # noqa: E402
    create_native_markdown_text_chunker,
)

MODULE_NAME = "heterarchy_alexandria_native"


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="heterarchy-alexandria-python-adapter-"
    ) as directory:
        _install_native_module(Path(directory))
        _document_parity()
        _chunking_parity()
        _hashing_parity()
        _note_index_compute_parity()
        _full_note_index_cutover_rehearsal()
        _graph_edge_parity()
        anyio.run(_graph_projection_parity)
        _reconciliation_candidate_parity()
    print(
        "python-native-adapter-parity: PASS "
        "document_cases=5 chunk_cases=5 hash_cases=5 note_index_cases=5 "
        "full_note_index_cutover_cases=1 graph_edge_cases=5 graph_projection_cases=1 "
        "reconciliation_candidate_cases=1"
    )
    return 0












def _document_parity() -> None:
    parser = create_native_markdown_document_parser()
    cases = [
        "# Plain\nBody\n",
        "---\ntitle: Case\ncount: 3\nratio: 1.5\nenabled: true\nnothing: null\ntags: [one, 2]\n---\n# Body\n",
        "---\r\ntitle: CRLF\r\ntags:\r\n  - one\r\n  - two\r\n---\r\n# Body\r\n",
        '---\ntitle: Quoted\ntags: ["a,b", c]\n---\n',
        "",
    ]
    for text in cases:
        first = parser.parse(text)
        second = parser.parse(text)
        if first != second:
            raise AssertionError(f"document native adapter is not deterministic for {text!r}")

    for invalid in (
        "---\ntitle: one\ntitle: two\n---\n",
        "---\ntitle: unterminated\n",
    ):
        first_message = _value_error_message(lambda invalid=invalid: parser.parse(invalid))
        second_message = _value_error_message(lambda invalid=invalid: parser.parse(invalid))
        if first_message != second_message:
            raise AssertionError("document native adapter error is not deterministic")


def _chunking_parity() -> None:
    chunker = create_native_markdown_text_chunker()
    cases = [
        ("Fallback", "", 1400, 160),
        ("Case", "# Case\n\n## Summary\nBody\n", 1400, 160),
        ("Unicode", "# 제목\n\n한국어 본문입니다.\n\n## 세부\n더 많은 내용\n", 20, 4),
        ("Fence", "# Title\n\n```md\n## code heading\n```\n\n## Real\nbody\n", 1400, 160),
        ("Long", "# Long\n\n" + ("abcdefghij" * 80), 120, 20),
    ]
    for title, content, max_chars, overlap_chars in cases:
        first = chunker.split(title=title, content=content, max_chars=max_chars, overlap_chars=overlap_chars)
        second = chunker.split(title=title, content=content, max_chars=max_chars, overlap_chars=overlap_chars)
        if first != second or any(len(chunk.content) > max_chars for chunk in first):
            raise AssertionError(f"chunk native adapter contract mismatch for {title!r}")


def _hashing_parity() -> None:
    batcher = create_native_text_hash_batcher()
    cases = (
        TextHashInput("empty", "Cases/Empty.md", ""),
        TextHashInput("ascii", "Cases/Ascii.md", "hello"),
        TextHashInput("unicode", "Cases/한글.md", "Hermes 기억"),
        TextHashInput("newline", "Cases/Newline.md", "a\nb\n"),
        TextHashInput("crlf", "Cases/CRLF.md", "a\r\nb\r\n"),
    )
    first = batcher.hash_texts(cases)
    second = batcher.hash_texts(cases)
    if first != second:
        raise AssertionError("hash native adapter is not deterministic")
    if any(len(result.content_hash) != 64 for result in first):
        raise AssertionError("hash native adapter returned an invalid SHA-256 digest")


def _note_index_compute_parity() -> None:
    provider = create_native_note_index_compute_provider()
    cases = (
        ("Projects/Canonical.md", "---\ntitle: Canonical Title\ntags: [one, two]\n---\n# Body Heading\nHello world\n\n"),
        ("Projects/HeadingFallback.md", "---\nstatus: active\n---\n# Heading Fallback\nBody\n"),
        ("Projects/Stem Fallback.md", "No level-one heading here.\nJust body text.\n"),
        ("Projects/한글.md", "---\ntitle: 한국어 노트\ncount: 3\n---\n# 시작\n본문입니다.\n\n## 세부\n더 많은 내용\n"),
        ("Projects/Empty.md", "---\ntitle: Empty Note\n---\n"),
    )
    expected_titles = ("Canonical Title", "Heading Fallback", "Stem Fallback", "한국어 노트", "Empty Note")
    for (relative_path, text), expected_title in zip(cases, expected_titles, strict=True):
        first = provider.compute(text, relative_path)
        second = provider.compute(text, relative_path)
        if first != second or first.title != expected_title or len(first.content_hash) != 64:
            raise AssertionError(f"note-index native adapter contract mismatch for {relative_path!r}")


def _full_note_index_cutover_rehearsal() -> None:
    text = """---
alexandria_type: job_plan
id: cutover-rehearsal-note
title: Cutover Rehearsal Note
status: active
project: heterarchy-alexandria
source: parity
tags: [rust, cutover]
---
# Cutover Rehearsal Note

This note links to [[Target Note]] and embeds ![[Evidence Note#Proof]].
"""
    with tempfile.TemporaryDirectory(prefix="heterarchy-note-index-cutover-") as directory:
        path = Path(directory) / "Cutover Rehearsal Note.md"
        path.write_text(text, encoding="utf-8")
        first = note_indexer_module.note_index_from_path(path, "Projects/Cutover Rehearsal Note.md", ".")
        second = note_indexer_module.note_index_from_path(path, "Projects/Cutover Rehearsal Note.md", ".")
    if first is None or first != second:
        raise AssertionError("full note-index Rust cutover is not deterministic")
    if first.note_id != "cutover-rehearsal-note" or first.title != "Cutover Rehearsal Note":
        raise AssertionError("full note-index Rust cutover returned unexpected note identity")
    if len(first.content_hash) != 64 or not first.edges:
        raise AssertionError("full note-index Rust cutover returned incomplete compute data")


def _graph_edge_parity() -> None:
    builder = create_native_obsidian_graph_edge_builder()
    cases = [
        ("ctx-current", "Alexandria/Contexts/Current.md", "Alexandria", {"source_refs": [{"id": "alexandria_start_here", "path": "START_HERE.md", "relation": "cites"}], "related": ["Skills/Active/Web Research.md"]}, "Read [[Prompts/System/Research|research prompt]] and [[START_HERE]]."),
        ("ctx-code", "Alexandria/Contexts/Projects/Current.md", "Alexandria", {}, "Visible [[Contexts/Source]].\n`inline [[Inline Example]]`\n<!-- [[HTML Comment]] -->\n%% [[Obsidian Comment]] %%\n```md\n[[Fenced Example]]\n```\n"),
        ("root-current", "Contexts/Current.md", ".", {"related": ["Skills/한국어 노트.md"]}, "Read [[START_HERE]] and [[Skills/한국어 노트|별칭]]."),
        ("external", "Contexts/Projects/Trader/Journal.md", ".", {"source_refs": ["evidence:run-123:1", "artifact:report-456"]}, "Evidence [[evidence:run-123:1]] and [[artifact:report-456]].\nReal [[Contexts/Projects/Trader/Index]].\n"),
        ("precedence", "Memory Compacts/Current.md", ".", {"source_refs": [{"source_id": "external", "detail_path": "Old.md"}], "source_ref_links": []}, "# Compact\n"),
    ]
    for note_id, relative_path, root, frontmatter, body in cases:
        first = builder.build(note_id=note_id, relative_path=relative_path, alexandria_root=root, frontmatter=frontmatter, body=body)
        second = builder.build(note_id=note_id, relative_path=relative_path, alexandria_root=root, frontmatter=frontmatter, body=body)
        if first != second or any(len(edge.edge_id) != 64 for edge in first):
            raise AssertionError(f"graph-edge native adapter contract mismatch for {relative_path!r}")


def _reconciliation_candidate_parity() -> None:
    provider = create_native_memory_reconciliation_candidate_compute_provider()
    result = provider.discover(
        items=(
            ReconciliationCandidateComputeItem(
                item_id="old",
                embedding=(1.0, 0.0),
                valid_from=datetime(2026, 8, 1, tzinfo=UTC),
                valid_to=datetime(2026, 8, 20, tzinfo=UTC),
                blocking_keys=("topic",),
                graph_neighbors=("shared", "x"),
            ),
            ReconciliationCandidateComputeItem(
                item_id="new",
                embedding=(0.8, 0.6),
                valid_from=datetime(2026, 8, 10, tzinfo=UTC),
                valid_to=datetime(2026, 8, 30, tzinfo=UTC),
                blocking_keys=("topic",),
                graph_neighbors=("shared", "y"),
                lineage_ancestors=("old",),
            ),
        ),
        policy=ReconciliationCandidateComputePolicy(
            vector_similarity_threshold=0.75,
            graph_similarity_threshold=0.3,
            max_block_size=16,
            max_candidates_per_item=8,
        ),
    )
    if len(result.candidate_pairs) != 1:
        raise AssertionError("reconciliation adapter must return one candidate pair")
    pair = result.candidate_pairs[0]
    if (pair.left_id, pair.right_id) != ("new", "old"):
        raise AssertionError(f"unexpected candidate identities: {pair!r}")
    if pair.lineage != "left_descends_from_right":
        raise AssertionError(f"unexpected lineage evidence: {pair.lineage!r}")
    if not pair.temporal_overlap or pair.vector_similarity != 0.8:
        raise AssertionError(f"unexpected candidate evidence: {pair!r}")




class _GraphSource:
    def __init__(
        self,
        notes: tuple[ObsidianNote, ...],
        edges: tuple[ObsidianEdge, ...],
    ) -> None:
        self._notes = notes
        self._edges = edges

    async def list_projection_notes(self) -> tuple[ObsidianNote, ...]:
        return self._notes

    async def list_projection_edges(self) -> tuple[ObsidianEdge, ...]:
        return self._edges


async def _graph_projection_parity() -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    notes = (
        _projection_note("source", "Alexandria/Contexts/Source.md", now),
        _projection_note(
            "target",
            "Alexandria/Skills/Active/Target.md",
            now,
            aliases=("Target Alias",),
        ),
        _projection_note(
            "error",
            "Alexandria/Contexts/Error.md",
            now,
            index_status=ObsidianIndexStatus.ERROR,
        ),
        _projection_note(
            "stale",
            "Alexandria/Contexts/Stale.md",
            now,
            index_status=ObsidianIndexStatus.STALE,
        ),
    )
    edges = (
        _projection_edge(
            "edge-resolved",
            "source",
            "Alexandria/Contexts/Source.md",
            "target",
            "old/path.md",
            now,
        ),
        _projection_edge(
            "edge-alias",
            "source",
            "Alexandria/Contexts/Source.md",
            None,
            "Target Alias.md",
            now,
        ),
        _projection_edge(
            "edge-missing",
            "source",
            "Alexandria/Contexts/Source.md",
            None,
            "Missing.md",
            now,
        ),
    )
    source = _GraphSource(notes, edges)
    actual = await ObsidianGraphProjectionSourceBuilder(
        source=source,
        batch_size=1,
        compute_provider=create_native_obsidian_graph_projection_compute_provider(),
    ).build()
    repeated = await ObsidianGraphProjectionSourceBuilder(
        source=source,
        batch_size=1,
        compute_provider=create_native_obsidian_graph_projection_compute_provider(),
    ).build()
    if actual != repeated:
        raise AssertionError("graph projection native adapter is not deterministic")
    if tuple(node.note_id for node in actual.projection.nodes) != ("source", "target"):
        raise AssertionError("graph projection native adapter returned unexpected nodes")
    if {edge.edge_id for edge in actual.projection.edges} != {
        "edge-alias",
        "edge-resolved",
    }:
        raise AssertionError("graph projection native adapter returned unexpected edges")
    if {issue.relative_path for issue in actual.issues} != {
        "Alexandria/Contexts/Error.md",
        "Missing.md",
    }:
        raise AssertionError("graph projection native adapter returned unexpected issues")
    if (
        actual.metrics.scanned,
        actual.metrics.indexed,
        actual.metrics.skipped,
        actual.metrics.errors,
    ) != (7, 4, 3, 2):
        raise AssertionError("graph projection native adapter returned unexpected metrics")


def _projection_note(
    note_id: str,
    relative_path: str,
    now: datetime,
    aliases: tuple[str, ...] = (),
    index_status: ObsidianIndexStatus = ObsidianIndexStatus.INDEXED,
) -> ObsidianNote:
    frontmatter: dict[str, object] = {}
    if aliases:
        frontmatter["aliases"] = list(aliases)
    return ObsidianNote(
        note_id=note_id,
        relative_path=relative_path,
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title=note_id.title(),
        status="active",
        tags=(),
        project="heterarchy-alexandria",
        source="adapter-parity",
        content_hash=f"hash-{note_id}",
        frontmatter=frontmatter,
        body=f"# {note_id}\n",
        index_status=index_status,
        error_message=(
            "frontmatter validation failed"
            if index_status is ObsidianIndexStatus.ERROR
            else None
        ),
        size_bytes=10,
        modified_at=now,
        indexed_at=now,
    )


def _projection_edge(
    edge_id: str,
    source_note_id: str,
    source_path: str,
    target_note_id: str | None,
    target_path: str,
    now: datetime,
) -> ObsidianEdge:
    return ObsidianEdge(
        edge_id=edge_id,
        source_note_id=source_note_id,
        source_path=source_path,
        target_note_id=target_note_id,
        target_path=target_path,
        relation=ObsidianRelationType.RELATED,
        confidence=0.8,
        source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
        created_at=now,
        indexed_at=now,
    )


def _value_error_message(operation: object) -> str:
    if not callable(operation):
        raise TypeError("operation must be callable")
    try:
        operation()
    except ValueError as exc:
        return str(exc)
    raise AssertionError("operation must raise ValueError")


def _install_native_module(temp_root: Path) -> None:
    configured = os.environ.get("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY")
    if configured is None or not configured.strip():
        raise RuntimeError("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY is required")
    library = Path(configured).resolve()
    if not library.is_file():
        raise FileNotFoundError(library)
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix, str) or not suffix:
        raise RuntimeError("Python EXT_SUFFIX is unavailable")
    destination = temp_root / f"{MODULE_NAME}{suffix}"
    shutil.copy2(library, destination)
    specification = importlib.util.spec_from_file_location(MODULE_NAME, destination)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load native extension from {destination}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    if not isinstance(module, ModuleType):
        raise RuntimeError("native extension loader returned an invalid module")
    module.__heterarchy_alexandria_native_library_source__ = str(library)
    sys.modules[MODULE_NAME] = module


if __name__ == "__main__":
    raise SystemExit(main())
