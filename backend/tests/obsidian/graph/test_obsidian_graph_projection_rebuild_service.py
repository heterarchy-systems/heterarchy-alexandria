"""Projection rebuild/status operation contracts for optional graph read models."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import anyio
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionBatch,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionIssue,
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionNode,
    ObsidianGraphProjectionSourceMetrics,
    ObsidianGraphProjectionSourceSnapshot,
    ObsidianGraphProjectionState,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphProjectionIssueCode,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.platform.config.app_config import AppConfig


class _FailingSourceBuilder:
    async def build(self) -> ObsidianGraphProjectionSourceSnapshot:
        raise AssertionError("disabled graph projection must not read source rows")


class _StaticSourceBuilder:
    def __init__(self, snapshot: ObsidianGraphProjectionSourceSnapshot) -> None:
        self.calls = 0
        self._snapshot = snapshot

    async def build(self) -> ObsidianGraphProjectionSourceSnapshot:
        self.calls += 1
        return self._snapshot


class _RecordingProjectionRepository:
    def __init__(self, *, fail_batch_index: int | None = None) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self._active = ObsidianGraphProjectionState(initialized=False)
        self._staged: dict[str, list[ObsidianGraphProjection]] = {}
        self._fail_batch_index = fail_batch_index
        self.fail_abort = False

    async def start_rebuild(self, *, run_id: str, projection_version: int) -> None:
        self.calls.append(("start", run_id, projection_version))
        self._staged[run_id] = []

    async def write_rebuild_batch(
        self,
        *,
        run_id: str,
        projection_version: int,
        batch: ObsidianGraphProjection,
    ) -> None:
        batch_index = len(self._staged[run_id])
        self.calls.append(("batch", run_id, batch))
        if self._fail_batch_index == batch_index:
            raise RuntimeError("neo4j write failed")
        self._staged[run_id].append(batch)

    async def complete_rebuild(
        self,
        *,
        run_id: str,
        projection_version: int,
        issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = (),
    ) -> None:
        self.calls.append(("complete", run_id, projection_version))
        batches = self._staged.pop(run_id)
        self._active = ObsidianGraphProjectionState(
            initialized=True,
            run_id=run_id,
            projection_version=projection_version,
            projection=ObsidianGraphProjection(
                nodes=tuple(node for item in batches for node in item.nodes),
                edges=tuple(edge for item in batches for edge in item.edges),
            ),
            issue_counts=issue_counts,
            issue_total=sum(item.count for item in issue_counts),
        )

    async def abort_rebuild(self, *, run_id: str) -> None:
        self.calls.append(("abort", run_id, 0))
        if self.fail_abort:
            raise OSError("password=do-not-report abort cleanup failed")
        self._staged.pop(run_id, None)

    async def state(self) -> ObsidianGraphProjectionState:
        return self._active

    async def snapshot(self) -> ObsidianGraphProjection:
        return self._active.projection


def _clock(values: tuple[float, ...]) -> Callable[[], float]:
    remaining = list(values)

    def now() -> float:
        return remaining.pop(0)

    return now


def _projection_snapshot() -> ObsidianGraphProjectionSourceSnapshot:
    node_a = ObsidianGraphProjectionNode(
        note_id="note-a",
        relative_path="Alexandria/Contexts/note-a.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title="A",
        status="active",
        project="heterarchy-alexandria",
    )
    node_b = ObsidianGraphProjectionNode(
        note_id="note-b",
        relative_path="Alexandria/Contexts/note-b.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title="B",
        status="active",
        project="heterarchy-alexandria",
    )
    edge = ObsidianGraphProjectionEdge(
        edge_id="edge-a-b",
        source_note_id="note-a",
        source_path="Alexandria/Contexts/note-a.md",
        target_note_id="note-b",
        target_path="Alexandria/Contexts/note-b.md",
        relation=ObsidianRelationType.RELATED,
        confidence=0.8,
        source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
    )
    issue = ObsidianGraphProjectionIssue(
        code=ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE,
        relative_path="Alexandria/Missing.md",
        edge_id="edge-missing",
        detail="target note is not in the healthy index",
    )
    return ObsidianGraphProjectionSourceSnapshot(
        projection=ObsidianGraphProjection(nodes=(node_a, node_b), edges=(edge,)),
        batches=(
            ObsidianGraphProjectionBatch(
                batch_index=0,
                projection=ObsidianGraphProjection(nodes=(node_a,), edges=(edge,)),
            ),
            ObsidianGraphProjectionBatch(
                batch_index=1,
                projection=ObsidianGraphProjection(nodes=(node_b,), edges=()),
            ),
        ),
        issues=(issue,),
        metrics=ObsidianGraphProjectionSourceMetrics(
            scanned=5,
            indexed=3,
            skipped=2,
            errors=1,
        ),
    )


def test_disabled_rebuild_and_status_do_not_build_source_or_require_repository() -> (
    None
):
    """Default-disabled mode should return explicit non-mutating responses."""

    async def scenario() -> tuple[object, object]:
        service = ObsidianGraphProjectionRebuildService(
            config=AppConfig(_env_file=None, graph_read_model="disabled"),
            source_builder=_FailingSourceBuilder(),
            repository=None,
            run_id_factory=lambda: "run-disabled",
            monotonic_seconds=_clock((100.0, 100.0)),
        )
        return await service.rebuild(include_issue_details=True), await service.status()

    report, status = anyio.run(scenario)

    assert report.status == "disabled"
    assert report.graph_read_model == "disabled"
    assert report.run_id == "run-disabled"
    assert report.scanned == 0
    assert report.indexed == 0
    assert report.updated == 0
    assert report.skipped == 0
    assert report.errors == ()
    assert report.duration_seconds == 0.0
    assert status.status == "disabled"
    assert status.enabled is False
    assert status.node_count == 0
    assert status.edge_count == 0


def test_enabled_rebuild_uses_builder_snapshot_and_reports_counts(
    tmp_path: Path,
) -> None:
    """Enabled rebuild should read only the index snapshot and write the adapter."""
    snapshot = _projection_snapshot()
    builder = _StaticSourceBuilder(snapshot)
    repository = _RecordingProjectionRepository()

    async def scenario() -> tuple[object, object]:
        service = ObsidianGraphProjectionRebuildService(
            config=AppConfig(
                _env_file=None,
                graph_read_model="neo4j",
                neo4j_uri="neo4j://example:7687",
                neo4j_username="neo4j",
                neo4j_password="local-test-password",
            ),
            source_builder=builder,
            repository=repository,
            run_id_factory=lambda: "run-enabled",
            monotonic_seconds=_clock((10.0, 12.5)),
        )
        return await service.rebuild(include_issue_details=True), await service.status()

    report, status = anyio.run(scenario)

    assert builder.calls == 1
    assert [call[0] for call in repository.calls] == [
        "start",
        "batch",
        "batch",
        "complete",
    ]
    assert {call[1] for call in repository.calls} == {"run-enabled"}
    assert report.status == "completed"
    assert report.graph_read_model == "neo4j"
    assert report.run_id == "run-enabled"
    assert report.scanned == 5
    assert report.indexed == 3
    assert report.updated == 3
    assert report.skipped == 2
    assert report.errors == ()
    assert tuple(issue.code for issue in report.issues) == ("missing_target_note",)
    assert report.issue_total == 1
    assert [(item.code, item.count) for item in report.issue_counts] == [
        (ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE, 1)
    ]
    assert report.issues_truncated is False
    assert report.duration_seconds == 2.5
    assert status.status == "ready"
    assert status.enabled is True
    assert status.node_count == 2
    assert status.edge_count == 1
    assert status.run_id == "run-enabled"
    assert status.projection_version == 1
    assert status.last_run_issue_total == 1
    assert [(item.code, item.count) for item in status.last_run_issue_counts] == [
        (ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE, 1)
    ]
    assert not (tmp_path / "vault").exists()


def test_enabled_rebuild_surfaces_adapter_failure_without_markdown_mutation(
    tmp_path: Path,
) -> None:
    """Adapter failures should be reported as operation errors, not vault writes."""
    builder = _StaticSourceBuilder(_projection_snapshot())
    repository = _RecordingProjectionRepository(fail_batch_index=1)

    async def scenario() -> object:
        service = ObsidianGraphProjectionRebuildService(
            config=AppConfig(
                _env_file=None,
                graph_read_model="neo4j",
                neo4j_uri="neo4j://example:7687",
                neo4j_username="neo4j",
                neo4j_password="local-test-password",
            ),
            source_builder=builder,
            repository=repository,
            run_id_factory=lambda: "run-failed",
            monotonic_seconds=_clock((20.0, 21.0)),
        )
        before = await repository.state()
        report = await service.rebuild(include_issue_details=True)
        return report, before, await repository.state()

    report, before, after = anyio.run(scenario)

    assert report.status == "failed"
    assert report.updated == 0
    assert tuple(issue.code for issue in report.issues) == ("missing_target_note",)
    assert tuple(error.code for error in report.errors) == ("adapter_write_failed",)
    assert "RuntimeError" in (report.errors[-1].detail or "")
    assert before == after
    assert repository.calls[-1][0] == "abort"
    assert not (tmp_path / "vault").exists()


def test_enabled_status_distinguishes_uninitialized_from_successful_empty() -> None:
    """Metadata, not item counts, distinguishes never-built from empty-ready."""
    repository = _RecordingProjectionRepository()

    async def scenario() -> tuple[object, object]:
        service = ObsidianGraphProjectionRebuildService(
            config=AppConfig(
                _env_file=None,
                graph_read_model="neo4j",
                neo4j_uri="neo4j://example:7687",
                neo4j_username="neo4j",
                neo4j_password="local-test-password",
            ),
            source_builder=_StaticSourceBuilder(
                ObsidianGraphProjectionSourceSnapshot(
                    projection=ObsidianGraphProjection(),
                    metrics=ObsidianGraphProjectionSourceMetrics(
                        scanned=0, indexed=0, skipped=0, errors=0
                    ),
                )
            ),
            repository=repository,
            run_id_factory=lambda: "run-empty",
        )
        before = await service.status()
        await service.rebuild()
        return before, await service.status()

    before, after = anyio.run(scenario)

    assert before.status == "uninitialized"
    assert before.run_id is None
    assert after.status == "ready"
    assert after.run_id == "run-empty"
    assert after.node_count == after.edge_count == 0


def test_source_failure_returns_redacted_typed_failed_report() -> None:
    """Source exceptions must not escape or reveal exception messages."""

    class _SecretFailingBuilder:
        async def build(self) -> ObsidianGraphProjectionSourceSnapshot:
            raise RuntimeError("password=do-not-report neo4j://secret")

    async def scenario() -> object:
        return await ObsidianGraphProjectionRebuildService(
            config=AppConfig(
                _env_file=None,
                graph_read_model="neo4j",
                neo4j_uri="neo4j://example:7687",
                neo4j_username="neo4j",
                neo4j_password="local-test-password",
            ),
            source_builder=_SecretFailingBuilder(),
            repository=_RecordingProjectionRepository(),
            run_id_factory=lambda: "run-source-failed",
        ).rebuild()

    report = anyio.run(scenario)

    assert report.status == "failed"
    assert report.run_id == "run-source-failed"
    assert report.scanned == report.indexed == report.updated == report.skipped == 0
    assert tuple(error.code for error in report.errors) == ("source_build_failed",)
    assert "do-not-report" not in (report.errors[0].detail or "")


def test_adapter_failure_preserves_primary_error_and_reports_abort_failure() -> None:
    """Cleanup failure should add a redacted diagnostic without masking primary."""
    repository = _RecordingProjectionRepository(fail_batch_index=0)
    repository.fail_abort = True

    async def scenario() -> object:
        return await ObsidianGraphProjectionRebuildService(
            config=AppConfig(
                _env_file=None,
                graph_read_model="neo4j",
                neo4j_uri="neo4j://example:7687",
                neo4j_username="neo4j",
                neo4j_password="local-test-password",
            ),
            source_builder=_StaticSourceBuilder(_projection_snapshot()),
            repository=repository,
            run_id_factory=lambda: "run-dual-failure",
        ).rebuild()

    report = anyio.run(scenario)

    assert report.status == "failed"
    assert tuple(error.code for error in report.errors[-2:]) == (
        "adapter_write_failed",
        "adapter_abort_failed",
    )
    assert "RuntimeError" in (report.errors[-2].detail or "")
    assert "OSError" in (report.errors[-1].detail or "")
    assert "do-not-report" not in (report.errors[-1].detail or "")


def test_rebuild_defaults_to_counted_diagnostics_without_large_detail_payload() -> None:
    """Default rebuild responses should summarize source issues and omit details."""

    async def scenario() -> object:
        service = ObsidianGraphProjectionRebuildService(
            config=AppConfig(
                _env_file=None,
                graph_read_model="neo4j",
                neo4j_uri="neo4j://example:7687",
                neo4j_username="neo4j",
                neo4j_password="local-test-password",
            ),
            source_builder=_StaticSourceBuilder(_projection_snapshot()),
            repository=_RecordingProjectionRepository(),
            run_id_factory=lambda: "run-summary",
        )
        return await service.rebuild()

    report = anyio.run(scenario)

    assert report.status == "completed"
    assert report.issue_total == 1
    assert report.issues == ()
    assert report.issues_truncated is True
    assert report.errors == ()
