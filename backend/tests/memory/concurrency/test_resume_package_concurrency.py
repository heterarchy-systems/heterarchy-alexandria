"""Concurrency and retry-contract tests for resume package creation."""

from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import anyio
import pytest

from app.memory.application.contexts.linting.context_lint import (
    ContextLintInput,
    lint_context,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageDraft,
    ResumePackageLineage,
)
from app.memory.application.memory_compacts.resume_package.resume_package_markdown import (
    parse_resume_package_markdown,
)
from app.memory.application.memory_compacts.resume_package.resume_package_service import (
    MemoryResumePackageService,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.memory.infrastructure.repositories.memory_compacts.note_store import (
    MemoryCompactNoteStore,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryCompactNotFoundError,
    MemoryResumePackageEvidenceNotFoundError,
    MemoryResumePackageRequestConflictError,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
COVERED_FROM = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
COVERED_TO = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
PROJECT = "heterarchy-alexandria"
LINEAGE_ID = "lineage-concurrency-1"
EVIDENCE_CONTEXT_ID = "ctx-evidence"
_COMPACT_DIR = "Alexandria/Memory Compacts"


class _ProcessBarrier(Protocol):
    def wait(self, timeout: float | None = None) -> int:
        """Wait for every participating process."""


class _ResultQueue(Protocol):
    def put(self, result: object) -> None:
        """Publish one process result."""


def _context_record(context_id: str) -> ContextRecord:
    """Build one stored evidence record.

    Args:
        context_id: Stored Context identifier.

    Returns:
        Context read model with deterministic observed fields.
    """
    return ContextRecord(
        id=context_id,
        kind=ContextKind.HANDOFF,
        title=f"Context {context_id}",
        summary="summary",
        content=f"Evidence content for {context_id}.",
        content_format=ContextContentFormat.MARKDOWN,
        project=PROJECT,
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="Hermes",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.HIGH,
        tags=[],
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata=ContextMetadataPayload(),
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


class _StaticEvidenceSource:
    """In-memory structural evidence seam standing in for ContextService."""

    def __init__(self, records: dict[str, ContextRecord]) -> None:
        self._records = records

    async def get(self, context_id: str) -> ContextRecord:
        """Return one stored record or raise the typed not-found error.

        Args:
            context_id: Stored Context identifier.

        Returns:
            Stored Context read model.

        Raises:
            MemoryResumePackageEvidenceNotFoundError: When the id is unknown.
        """
        record = self._records.get(context_id)
        if record is None:
            raise MemoryResumePackageEvidenceNotFoundError(context_id)
        return record


def _compact_service(vault_path: Path) -> MemoryCompactService:
    """Build the compact facade over one vault.

    Args:
        vault_path: Obsidian vault root path.

    Returns:
        Memory Compact application facade.
    """
    return MemoryCompactService(
        repository=ObsidianMemoryCompactRepository(
            vault_path=vault_path,
            relative_dir=_COMPACT_DIR,
        )
    )


def _service(
    vault_path: Path,
    *,
    start_gate: _ProcessBarrier | None = None,
) -> MemoryResumePackageService:
    """Build the resume package service over one vault.

    Args:
        vault_path: Obsidian vault root path.
        start_gate: Optional process barrier awaited before the guarded
            critical section, widening the lock contention window.

    Returns:
        Resume package service.
    """

    class _GatedService(MemoryResumePackageService):
        """Service that synchronizes processes before the guarded section."""

        async def _collect_evidence(
            self,
            evidence_context_ids: tuple[str, ...],
        ):
            if start_gate is not None:
                start_gate.wait(timeout=10)
            return await super()._collect_evidence(evidence_context_ids)

    return _GatedService(
        compact_service=_compact_service(vault_path),
        evidence_source=_StaticEvidenceSource(
            {EVIDENCE_CONTEXT_ID: _context_record(EVIDENCE_CONTEXT_ID)}
        ),
    )


def _draft(*, summary: str, request_id: str | None = None) -> ResumePackageDraft:
    """Build one deterministic draft for the shared lineage.

    Args:
        summary: Package summary distinguishing content variants.
        request_id: Optional retry-fencing identity.

    Returns:
        Resume package draft.
    """
    return ResumePackageDraft(
        project=PROJECT,
        goal="Prove the resume package concurrency contract",
        summary=summary,
        current_state="Whole critical section runs under the creation guard",
        next_single_action="Verify exactly-once sealing under concurrency",
        covered_from=COVERED_FROM,
        covered_to=COVERED_TO,
        lineage=ResumePackageLineage(lineage_id=LINEAGE_ID, worker_id="worker-1"),
        evidence_context_ids=(EVIDENCE_CONTEXT_ID,),
        request_id=request_id,
    )


def _create_in_process(
    vault_path: str,
    summary: str,
    request_id: str | None,
    start_gate: _ProcessBarrier,
    result_queue: _ResultQueue,
) -> None:
    """Create one resume package in a spawned process and report the seal.

    Args:
        vault_path: Obsidian vault root path.
        summary: Content-variant summary for this process.
        request_id: Retry-fencing identity for this process.
        start_gate: Barrier both processes wait on before creating.
        result_queue: Queue receiving the outcome tuple. Success carries
            (id, revision, deduplicated); the request-conflict rejection is
            reported as ``("conflict", 0, False)``.
    """

    async def scenario() -> tuple[str, int, bool]:
        service = _service(Path(vault_path), start_gate=start_gate)
        try:
            seal = await service.create_resume_package(
                _draft(summary=summary, request_id=request_id)
            )
        except MemoryResumePackageRequestConflictError:
            return "conflict", 0, False
        return seal.package_id, seal.package_revision, seal.deduplicated

    result = anyio.run(scenario)
    result_queue.put(result)


def test_identical_retry_across_processes_returns_original_identity(
    tmp_path: Path,
) -> None:
    """Two processes racing the same draft must seal one revision once."""
    vault_path = tmp_path / "vault"
    process_context = multiprocessing.get_context("spawn")
    start_gate = process_context.Barrier(2)
    result_queue = process_context.Queue()
    processes = [
        process_context.Process(
            target=_create_in_process,
            args=(
                str(vault_path),
                "Shared retry draft",
                "req-shared",
                start_gate,
                result_queue,
            ),
        )
        for _ in range(2)
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        assert [process.exitcode for process in processes] == [0, 0]
        results = [result_queue.get(timeout=5) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()

    package_ids = {result[0] for result in results}
    revisions = {result[1] for result in results}
    deduplicated = sorted(result[2] for result in results)
    note_paths = list((vault_path / _COMPACT_DIR).rglob("*.md"))

    assert len(package_ids) == 1
    assert revisions == {1}
    assert deduplicated == [False, True]
    assert len(note_paths) == 1


def test_distinct_content_across_processes_seals_sequential_revisions(
    tmp_path: Path,
) -> None:
    """Concurrent distinct content must produce revisions 1 and 2, one CURRENT."""
    vault_path = tmp_path / "vault"
    process_context = multiprocessing.get_context("spawn")
    start_gate = process_context.Barrier(2)
    result_queue = process_context.Queue()
    summaries = ("Distinct content alpha", "Distinct content beta")
    processes = [
        process_context.Process(
            target=_create_in_process,
            args=(
                str(vault_path),
                summary,
                f"req-{summary.rsplit(' ', 1)[-1]}",
                start_gate,
                result_queue,
            ),
        )
        for summary in summaries
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        assert [process.exitcode for process in processes] == [0, 0]
        results = [result_queue.get(timeout=5) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()

    by_revision = {result[1]: (result[0], result[2]) for result in results}
    note_paths = list((vault_path / _COMPACT_DIR).rglob("*.md"))
    bodies = {path.name: path.read_text(encoding="utf-8") for path in note_paths}

    assert sorted(by_revision) == [1, 2]
    first_id = by_revision[1][0]
    second_id = by_revision[2][0]
    second_body = next(body for name, body in bodies.items() if second_id in name)
    assert f"previous_package_id: {first_id}" in second_body
    assert len(note_paths) == 2

    async def read_current() -> str | None:
        current = await _compact_service(vault_path).current(project=PROJECT)
        return None if current is None else current.id

    current_id = anyio.run(read_current)
    assert current_id == second_id


def test_same_request_id_across_processes_yields_one_conflict(
    tmp_path: Path,
) -> None:
    """Two processes with one request id but different content: one wins."""
    vault_path = tmp_path / "vault"
    process_context = multiprocessing.get_context("spawn")
    start_gate = process_context.Barrier(2)
    result_queue = process_context.Queue()
    summaries = ("Fenced alpha content", "Fenced beta content")
    processes = [
        process_context.Process(
            target=_create_in_process,
            args=(
                str(vault_path),
                summary,
                "req-fenced",
                start_gate,
                result_queue,
            ),
        )
        for summary in summaries
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        assert [process.exitcode for process in processes] == [0, 0]
        results = [result_queue.get(timeout=5) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()

    successes = [result for result in results if result[0] != "conflict"]
    conflicts = [result for result in results if result[0] == "conflict"]
    note_paths = list((vault_path / _COMPACT_DIR).rglob("*.md"))

    assert len(successes) == 1
    assert len(conflicts) == 1
    assert successes[0][1] == 1
    assert successes[0][2] is False
    assert len(note_paths) == 1


def test_lost_response_retry_returns_original_identity_without_revision_bump(
    tmp_path: Path,
) -> None:
    """Retrying a lost response must replay the original sealed identity."""

    async def scenario() -> tuple[int, int, bool, bool]:
        vault = tmp_path / "vault"
        service = _service(vault)
        first = await service.create_resume_package(
            _draft(summary="Lost response draft", request_id="req-lost")
        )
        retry = await service.create_resume_package(
            _draft(summary="Lost response draft", request_id="req-lost")
        )
        _listed, total = await _compact_service(vault).list_compacts(project=PROJECT)
        return (
            total,
            retry.package_revision,
            retry.package_id == first.package_id,
            retry.deduplicated,
        )

    total, retry_revision, same_identity, deduplicated = anyio.run(scenario)

    assert total == 1
    assert retry_revision == 1
    assert same_identity
    assert deduplicated


def test_same_request_id_with_different_content_is_rejected(tmp_path: Path) -> None:
    """A sealed request id retried with new content must fail typed."""

    async def scenario() -> tuple[int, int]:
        vault = tmp_path / "vault"
        service = _service(vault)
        first = await service.create_resume_package(
            _draft(summary="Fenced draft original", request_id="req-fence")
        )
        with pytest.raises(MemoryResumePackageRequestConflictError):
            await service.create_resume_package(
                _draft(summary="Fenced draft mutated", request_id="req-fence")
            )
        _listed, total = await _compact_service(vault).list_compacts(project=PROJECT)
        return first.package_revision, total

    first_revision, total = anyio.run(scenario)

    assert first_revision == 1
    assert total == 1


def test_failure_between_store_effects_never_yields_two_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash after supersede but before the new CURRENT write recovers on retry."""
    vault = tmp_path / "vault"

    async def scenario() -> tuple[int, str]:
        service = _service(vault)
        first = await service.create_resume_package(
            _draft(summary="Crash recovery revision one", request_id="req-crash-1")
        )
        original_write = MemoryCompactNoteStore.write
        superseded_seen = False

        def failing_write(store: MemoryCompactNoteStore, compact) -> None:
            nonlocal superseded_seen
            if compact.status is MemoryCompactStatus.SUPERSEDED:
                superseded_seen = True
            if compact.status is MemoryCompactStatus.CURRENT:
                assert superseded_seen
                raise RuntimeError("injected failure between store effects")
            original_write(store, compact)

        with monkeypatch.context() as patch_context:
            patch_context.setattr(MemoryCompactNoteStore, "write", failing_write)
            try:
                await service.create_resume_package(
                    _draft(
                        summary="Crash recovery revision two",
                        request_id="req-crash-2",
                    )
                )
            except RuntimeError as exc:
                assert "injected" in str(exc)
            else:
                raise AssertionError("injected failure did not fire")

        with pytest.raises(MemoryCompactNotFoundError):
            await _compact_service(vault).current(project=PROJECT)
        assert first.package_revision == 1
        retry = await service.create_resume_package(
            _draft(summary="Crash recovery revision two", request_id="req-crash-2")
        )
        recovered_current = await _compact_service(vault).current(project=PROJECT)
        listed, total = await _compact_service(vault).list_compacts(project=PROJECT)
        assert recovered_current is not None
        assert recovered_current.id == retry.package_id
        assert total == 2
        assert {item.status for item in listed} == {
            MemoryCompactStatus.SUPERSEDED,
            MemoryCompactStatus.CURRENT,
        }
        parsed = parse_resume_package_markdown(retry.markdown_body)
        assert parsed.previous_package_id == first.package_id
        return retry.package_revision, parsed.previous_package_id

    retry_revision, previous_id = anyio.run(scenario)

    assert retry_revision == 2
    assert previous_id


def test_reopened_view_exposes_sealed_revision_parsed_from_body(
    tmp_path: Path,
) -> None:
    """The retrieval read path must parse the sealed lineage revision."""
    vault = tmp_path / "vault"

    async def scenario() -> tuple[int, int, str]:
        service = _service(vault)
        first = await service.create_resume_package(
            _draft(summary="Parse revision one")
        )
        second = await service.create_resume_package(
            _draft(summary="Parse revision two")
        )
        first_view = await service.get_resume_package(first.package_id)
        second_view = await service.get_resume_package(second.package_id)
        parsed = parse_resume_package_markdown(second_view.markdown_body)
        lint = lint_context(
            ContextLintInput(
                kind=ContextKind.HANDOFF,
                title="Resume package",
                content=second_view.markdown_body,
                summary=second_view.markdown_body.splitlines()[1],
                project=PROJECT,
            )
        )
        assert lint.ok is True
        assert second_view.request_id is None
        return (
            first_view.lineage.package_revision or 0,
            second_view.lineage.package_revision or 0,
            parsed.previous_package_id or "",
        )

    first_revision, second_revision, previous_id = anyio.run(scenario)

    assert (first_revision, second_revision) == (1, 2)
    assert previous_id
