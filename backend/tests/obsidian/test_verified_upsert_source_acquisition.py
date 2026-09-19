"""Verified upsert source-acquisition instrumentation (parse-once boundary).

Counts Markdown parses, Rust FFI crossings, managed-source reads, and SQL
statements for one verified upsert so the parse-once boundary from the
Knowledge Compiler migration stays measurable and regression-guarded.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import anyio
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.application.graph.relations.native_obsidian_graph_edge_builder import (
    NativeObsidianGraphEdgeBuilder,
)
from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    source_matches_hash,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    _read_source_text,
    note_index_from_path,
)
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.notes.obsidian_verified_upsert_service import (
    ObsidianVerifiedUpsertService,
)
from app.obsidian.application.service.notes.obsidian_write_target_resolver import (
    ObsidianWriteTargetResolver,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianEdgeIndex
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedUpsertOperation,
    ObsidianVerifiedUpsertRequest,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.frontmatter import MarkdownDocument
from app.obsidian.infrastructure.markdown.native_frontmatter import (
    NativeMarkdownDocumentParser,
)
from app.obsidian.infrastructure.markdown.native_note_index_compute import (
    NativeNoteIndexComputeProvider,
)
from app.obsidian.infrastructure.markdown.note_index_compute_contracts import (
    NoteIndexComputeResult,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import (
    NativeTextHashBatcher,
    TextHashInput,
    TextHashResult,
)
from app.shared.infrastructure.database import Database
from app.shared.infrastructure.postgres_advisory_lock import PostgresAdvisoryLock
from app.shared.types.extra_types import JSONObject


def _request(
    *,
    key: str,
    body: str,
    entity: str = "ETH",
    expected: str | None = None,
) -> ObsidianVerifiedUpsertRequest:
    """Build one real managed-note request."""
    return ObsidianVerifiedUpsertRequest(
        identity=ObsidianLogicalIdentity(
            project="Project",
            report="Morning Read",
            date="2026-09-08",
            entity=entity,
        ),
        title=f"{entity} Morning Read",
        body=body,
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        idempotency_key=key,
        expected_content_hash=expected,
    )


def _real_service(
    database: Database,
    session: AsyncSession,
    vault_path: Path,
) -> tuple[ObsidianVerifiedUpsertService, ObsidianService]:
    """Assemble the real PostgreSQL/Markdown authority for one session."""
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    store = ObsidianVaultConfigStore(
        default_vault_path=str(vault_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    coordinator = IndexMaintenanceCoordinator(
        process_lock=PostgresAdvisoryLock(
            database.engine,
            namespace="heterarchy-alexandria:test-verified-upsert-acquisition",
        )
    )
    obsidian = ObsidianService(
        repository=repository,
        vault_config_store=store,
        index_maintenance_coordinator=coordinator,
    )
    service = ObsidianVerifiedUpsertService(
        obsidian_service=obsidian,
        canonical_identity_service=ObsidianCanonicalIdentityService(
            obsidian_service=obsidian,
            vault_config_store=store,
        ),
        vault_config_store=store,
        index_maintenance_coordinator=coordinator,
        commit_projection=session.commit,
        rollback_projection=session.rollback,
    )
    return service, obsidian


class _AcquisitionCounters:
    """Count Markdown parses, FFI crossings, reads, and SQL statements."""

    def __init__(self) -> None:
        """Initialize all counters to zero."""
        self.reset()

    def reset(self) -> None:
        """Begin a new measured operation."""
        self.index_parses = 0
        self.analysis_parses = 0
        self.edge_ffis = 0
        self.hash_ffis = 0
        self.indexer_reads = 0
        self.verification_reads = 0
        self.id_fallback_reads = 0
        self.sql_statements = 0

    @property
    def markdown_parses(self) -> int:
        """Return total source interpretations (index + analysis parses)."""
        return self.index_parses + self.analysis_parses

    @property
    def tracked_ffi_crossings(self) -> int:
        """Return crossings through the measured parse, edge, and hash adapters."""
        return self.markdown_parses + self.edge_ffis + self.hash_ffis

    def summary(self) -> str:
        """Return one human-readable measurement line."""
        return (
            f"parses={self.markdown_parses} "
            f"(index={self.index_parses} analysis={self.analysis_parses}) "
            f"tracked_ffi={self.tracked_ffi_crossings} "
            f"(edges={self.edge_ffis} hashes={self.hash_ffis}) "
            f"tracked_reads={self.indexer_reads + self.verification_reads + self.id_fallback_reads} "
            f"(indexer={self.indexer_reads} verification={self.verification_reads} "
            f"id_fallback={self.id_fallback_reads}) "
            f"sql={self.sql_statements}"
        )


@pytest.fixture()
def acquisition_counters(monkeypatch: pytest.MonkeyPatch) -> _AcquisitionCounters:
    """Install parse/FFI/read/SQL counters around the real native adapters."""
    counters = _AcquisitionCounters()

    index_compute = NativeNoteIndexComputeProvider.compute

    def count_index_compute(
        self: NativeNoteIndexComputeProvider,
        text: str,
        relative_path: str,
        *,
        include_chunks: bool = True,
    ) -> NoteIndexComputeResult:
        counters.index_parses += 1
        return index_compute(self, text, relative_path, include_chunks=include_chunks)

    monkeypatch.setattr(NativeNoteIndexComputeProvider, "compute", count_index_compute)

    analysis_parse = NativeMarkdownDocumentParser.parse

    def count_analysis_parse(
        self: NativeMarkdownDocumentParser, text: str
    ) -> MarkdownDocument:
        counters.analysis_parses += 1
        return analysis_parse(self, text)

    monkeypatch.setattr(NativeMarkdownDocumentParser, "parse", count_analysis_parse)

    edge_build = NativeObsidianGraphEdgeBuilder.build

    def count_edge_build(
        self: NativeObsidianGraphEdgeBuilder,
        note_id: str,
        relative_path: str,
        alexandria_root: str,
        frontmatter: JSONObject,
        body: str,
    ) -> list[ObsidianEdgeIndex]:
        counters.edge_ffis += 1
        return edge_build(
            self, note_id, relative_path, alexandria_root, frontmatter, body
        )

    monkeypatch.setattr(NativeObsidianGraphEdgeBuilder, "build", count_edge_build)

    hash_texts = NativeTextHashBatcher.hash_texts

    def count_hash_texts(
        self: NativeTextHashBatcher, items: tuple[TextHashInput, ...]
    ) -> tuple[TextHashResult, ...]:
        counters.hash_ffis += 1
        return hash_texts(self, items)

    monkeypatch.setattr(NativeTextHashBatcher, "hash_texts", count_hash_texts)

    def count_indexer_read(path: Path, max_source_bytes: int | None) -> str:
        counters.indexer_reads += 1
        return _read_source_text(path, max_source_bytes=max_source_bytes)

    monkeypatch.setattr(
        "app.obsidian.application.notes.obsidian_note_indexer._read_source_text",
        count_indexer_read,
    )

    def count_verification_read(path: Path, max_source_bytes: int | None) -> str:
        counters.verification_reads += 1
        return _read_source_text(path, max_source_bytes=max_source_bytes)

    monkeypatch.setattr(
        "app.obsidian.application.notes.lifecycle.obsidian_authoritative_read._read_source_text",
        count_verification_read,
    )

    id_fallback = ObsidianWriteTargetResolver.note_id_from_existing_file

    def count_id_fallback(self: ObsidianWriteTargetResolver, path: Path) -> str | None:
        if path.exists() and not path.is_symlink():
            counters.id_fallback_reads += 1
        return id_fallback(self, path)

    monkeypatch.setattr(
        ObsidianWriteTargetResolver,
        "note_id_from_existing_file",
        count_id_fallback,
    )

    return counters


def _track_sql(database: Database, counters: _AcquisitionCounters) -> None:
    """Attach one SQL statement counter to the database engine."""

    def count_statement(*args: object) -> None:
        counters.sql_statements += 1

    event.listen(
        database.engine.sync_engine,
        "before_cursor_execute",
        count_statement,
    )


def test_verified_upsert_source_acquisition_parse_budget(
    tmp_path: Path,
    acquisition_counters: _AcquisitionCounters,
) -> None:
    """One verified upsert must stay inside the parse-once source budget."""

    async def scenario() -> tuple[str, str, str]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "acquisition-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            service, _ = _real_service(database, session, vault_path)
            seed = await service.upsert(_request(key="seed-note", body="seed body"))

            counters = acquisition_counters
            _track_sql(database, counters)

            counters.reset()
            created = await service.upsert(
                _request(key="acq-create", body="fresh fact", entity="BTC")
            )
            create_report = counters.summary()
            assert counters.markdown_parses == 2, create_report
            assert counters.edge_ffis == 1, create_report
            assert counters.verification_reads == 1, create_report

            counters.reset()
            updated = await service.upsert(
                _request(
                    key="acq-update",
                    body="changed fact",
                    entity="BTC",
                    expected=created.content_hash,
                )
            )
            update_report = counters.summary()
            assert counters.markdown_parses == 3, update_report
            assert counters.edge_ffis == 1, update_report
            assert counters.verification_reads == 2, update_report
            assert counters.id_fallback_reads == 0, update_report

            counters.reset()
            replay = await service.upsert(
                _request(
                    key="acq-update",
                    body="changed fact",
                    entity="BTC",
                    expected=created.content_hash,
                )
            )
            replay_report = counters.summary()
            assert counters.markdown_parses == 1, replay_report
            assert counters.edge_ffis == 0, replay_report
            assert replay.operation is ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY
            assert replay.note_id == updated.note_id
            assert replay.content_hash == updated.content_hash
            assert updated.operation is ObsidianVerifiedUpsertOperation.UPDATED
            assert seed.content_hash != created.content_hash
        finally:
            await session.close()
            await database.shutdown()

        return create_report, update_report, replay_report

    create_report, update_report, replay_report = anyio.run(scenario)
    print(f"\nCREATE:  {create_report}")
    print(f"UPDATE:  {update_report}")
    print(f"REPLAY:  {replay_report}")

    # Parse-once budget: each distinct byte content is interpreted exactly once.
    # CREATE: snapshot(existing note) + post-write index; the post-commit
    #   readback is hash-verified instead of re-parsing.
    # UPDATE: snapshot(2 notes, old target content) + post-write index of the
    #   new content; both former same-byte re-parses are hash-verified reads.


@pytest.mark.parametrize("replacement_body", ["modified body", "manually edited body"])
def test_source_matches_hash_rejects_drift(
    tmp_path: Path,
    replacement_body: str,
) -> None:
    """A changed or grown source must fail the bounded hash verification."""

    async def scenario() -> tuple[bool, bool]:
        vault_path = tmp_path / "drift-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        note_path = vault_path / "Alexandria" / "note.md"
        note_path.write_text(
            "---\nid: drift-1\nalexandria_type: job_plan\ntitle: Drift\n"
            "---\n\noriginal body\n",
            encoding="utf-8",
        )
        payload = note_index_from_path(
            note_path,
            "Alexandria/note.md",
            alexandria_root="Alexandria",
        )
        assert payload is not None and payload.source_hash
        matching = source_matches_hash(
            vault_path,
            "Alexandria/note.md",
            "Alexandria",
            payload.source_hash,
            max_source_bytes=payload.size_bytes,
        )
        note_path.write_text(
            "---\nid: drift-1\nalexandria_type: job_plan\ntitle: Drift\n"
            f"---\n\n{replacement_body}\n",
            encoding="utf-8",
        )
        drifted = source_matches_hash(
            vault_path,
            "Alexandria/note.md",
            "Alexandria",
            payload.source_hash,
            max_source_bytes=payload.size_bytes,
        )
        return matching, drifted

    matching, drifted = anyio.run(scenario)
    assert matching is True
    assert drifted is False


def test_verified_snapshot_cannot_be_reused_for_another_path(tmp_path: Path) -> None:
    """Equal source text does not prove path-dependent titles or identity."""

    async def scenario() -> None:
        database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
        await database.initialize()
        session = database.session()
        vault = tmp_path / "path-bound-vault"
        (vault / "Alexandria").mkdir(parents=True)
        text = "---\nid: path-bound\nalexandria_type: job_plan\n---\nbody\n"
        first = vault / "Alexandria/First.md"
        first.write_text(text, encoding="utf-8")
        (vault / "Alexandria/Second.md").write_text(text, encoding="utf-8")
        payload = note_index_from_path(first, "Alexandria/First.md", "Alexandria")
        assert payload is not None
        try:
            _, obsidian = _real_service(database, session, vault)
            assert (
                await obsidian.read_note_by_path_verified(
                    "Alexandria/Second.md", payload
                )
                is None
            )
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_verified_write_readback_rejects_changed_projection(tmp_path: Path) -> None:
    """A matching source hash cannot authenticate different indexed metadata."""

    async def scenario() -> None:
        database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
        await database.initialize()
        session = database.session()
        vault = tmp_path / "projection-drift-vault"
        (vault / "Alexandria").mkdir(parents=True)
        try:
            service, obsidian = _real_service(database, session, vault)
            created = await service.upsert(
                _request(key="projection-drift", body="source body")
            )
            note = await obsidian.read_note(created.note_id)
            payload = note_index_from_path(
                vault / note.relative_path, note.relative_path, "Alexandria"
            )
            assert payload is not None and payload.source_hash
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            await repository.upsert_note(replace(payload, body="stale indexed body"))
            await session.commit()
            assert (
                await obsidian.read_note_from_write_evidence(
                    note.relative_path,
                    source_hash=payload.source_hash,
                    expected_note=note,
                )
                is None
            )
            authoritative = await obsidian.read_note_by_path(note.relative_path)
            assert authoritative.body == note.body
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)
