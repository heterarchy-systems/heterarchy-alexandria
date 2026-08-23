"""Explicit rebuild/status operations for the optional graph projection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal
from uuid import uuid4

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionIssue,
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionSourceSnapshot,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.platform.config.app_config import AppConfig
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)

GraphProjectionRebuildStatus = Literal["completed", "disabled", "failed"]
GraphProjectionStatus = Literal["disabled", "uninitialized", "ready", "unavailable"]
PROJECTION_VERSION = 1


class ObsidianGraphProjectionSourceBuilderProtocol(ABC):
    """Projection source builder behavior consumed by rebuild operations."""

    @abstractmethod
    async def build(self) -> ObsidianGraphProjectionSourceSnapshot:
        """Return one read-only source snapshot for projection rebuild.

        Returns:
            Typed projection source snapshot.
        """


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphProjectionOperationError:
    """One non-secret graph projection operation diagnostic."""

    code: str
    relative_path: str | None = None
    note_id: str | None = None
    edge_id: str | None = None
    detail: str | None = None


@dataclass(slots=True, kw_only=True)
class ObsidianGraphProjectionRebuildReport:
    """Stable result contract for one explicit projection rebuild request."""

    status: GraphProjectionRebuildStatus
    graph_read_model: Literal["disabled", "neo4j"]
    run_id: str
    scanned: int
    indexed: int
    updated: int
    skipped: int
    duration_seconds: float
    issue_total: int = 0
    issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = field(
        default_factory=tuple
    )
    issues: tuple[ObsidianGraphProjectionOperationError, ...] = field(
        default_factory=tuple
    )
    issues_truncated: bool = False
    errors: tuple[ObsidianGraphProjectionOperationError, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        """Normalize rebuild diagnostics to immutable tuples."""
        self.errors = tuple(self.errors)
        self.issues = tuple(self.issues)
        self.issue_counts = tuple(self.issue_counts)


@dataclass(slots=True, kw_only=True)
class ObsidianGraphProjectionStatusReport:
    """Stable status contract for the optional graph projection."""

    status: GraphProjectionStatus
    graph_read_model: Literal["disabled", "neo4j"]
    enabled: bool
    node_count: int
    edge_count: int
    run_id: str | None = None
    projection_version: int | None = None
    last_run_issue_total: int = 0
    last_run_issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = field(
        default_factory=tuple
    )
    errors: tuple[ObsidianGraphProjectionOperationError, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        """Normalize status diagnostics to immutable tuples."""
        self.errors = tuple(self.errors)
        self.last_run_issue_counts = tuple(self.last_run_issue_counts)


class ObsidianGraphProjectionRebuildService:
    """Coordinate read-only source building with the optional projection adapter."""

    def __init__(
        self,
        config: AppConfig,
        source_builder: ObsidianGraphProjectionSourceBuilderProtocol,
        repository: IObsidianGraphProjectionRepository | None,
        run_id_factory: Callable[[], str] | None = None,
        monotonic_seconds: Callable[[], float] | None = None,
        index_maintenance_coordinator: IndexMaintenanceCoordinator | None = None,
    ) -> None:
        """Create the graph projection operation service.

        Args:
            config: Typed application configuration.
            source_builder: Read-only builder over the current relational index/cache.
            repository: Optional graph projection adapter; absent when disabled.
            run_id_factory: Optional deterministic run id source for tests.
            monotonic_seconds: Optional monotonic clock for duration measurement.
            index_maintenance_coordinator: Index maintenance coordinator used by this operation.
        """
        self._config = config
        self._source_builder = source_builder
        self._repository = repository
        self._run_id_factory = run_id_factory or (lambda: str(uuid4()))
        self._monotonic_seconds = monotonic_seconds or monotonic
        self._index_maintenance_coordinator = (
            index_maintenance_coordinator or IndexMaintenanceCoordinator()
        )

    async def rebuild(
        self,
        include_issue_details: bool = False,
        issue_limit: int = 100,
    ) -> ObsidianGraphProjectionRebuildReport:
        """Run one explicit rebuild or return an explicit disabled response.

        Args:
            include_issue_details: Include a bounded sample of non-fatal issues.
            issue_limit: Maximum issue details to return when sampling is enabled.

        Returns:
            Typed rebuild report with deterministic counts and diagnostics.
        """
        if issue_limit < 1:
            raise ValueError("issue_limit must be greater than zero")
        repository = self._repository
        if self._config.graph_read_model == "disabled" or repository is None:
            return self._disabled_report()
        async with self._index_maintenance_coordinator.operation(
            "graph_projection_rebuild"
        ):
            return await self._rebuild_enabled(
                repository=repository,
                include_issue_details=include_issue_details,
                issue_limit=issue_limit,
            )

    def _disabled_report(self) -> ObsidianGraphProjectionRebuildReport:
        """Execute disabled report.

        Returns:
            ObsidianGraphProjectionRebuildReport result produced by disabled report.
        """
        run_id = self._run_id_factory()
        started_at = self._monotonic_seconds()
        return ObsidianGraphProjectionRebuildReport(
            status="disabled",
            graph_read_model=self._config.graph_read_model,
            run_id=run_id,
            scanned=0,
            indexed=0,
            updated=0,
            skipped=0,
            duration_seconds=_duration(started_at, self._monotonic_seconds()),
        )

    async def _rebuild_enabled(
        self,
        repository: IObsidianGraphProjectionRepository,
        include_issue_details: bool,
        issue_limit: int,
    ) -> ObsidianGraphProjectionRebuildReport:
        """Build and activate one graph run while holding maintenance ownership.

        Args:
            repository: Repository used by this operation.
            include_issue_details: Whether to include issue details.
            issue_limit: Issue limit used by this operation.

        Returns:
            ObsidianGraphProjectionRebuildReport result produced by rebuild enabled.
        """
        run_id = self._run_id_factory()
        started_at = self._monotonic_seconds()
        try:
            source_snapshot = await self._source_builder.build()
        except Exception as exc:
            return ObsidianGraphProjectionRebuildReport(
                status="failed",
                graph_read_model=self._config.graph_read_model,
                run_id=run_id,
                scanned=0,
                indexed=0,
                updated=0,
                skipped=0,
                errors=(_operation_failure("source_build_failed", exc),),
                duration_seconds=_duration(started_at, self._monotonic_seconds()),
            )
        scanned = source_snapshot.metrics.scanned
        indexed = source_snapshot.metrics.indexed
        skipped = source_snapshot.metrics.skipped
        issue_counts = _issue_counts(source_snapshot.issues)
        all_issues = tuple(_operation_issue(issue) for issue in source_snapshot.issues)
        issues = all_issues[:issue_limit] if include_issue_details else ()
        issues_truncated = len(issues) < len(all_issues)
        try:
            await repository.start_rebuild(
                run_id=run_id,
                projection_version=PROJECTION_VERSION,
            )
            for batch in source_snapshot.batches:
                await repository.write_rebuild_batch(
                    run_id=run_id,
                    projection_version=PROJECTION_VERSION,
                    batch=batch.projection,
                )
            await repository.complete_rebuild(
                run_id=run_id,
                projection_version=PROJECTION_VERSION,
                issue_counts=issue_counts,
            )
        except Exception as exc:
            failure_errors = (_operation_failure("adapter_write_failed", exc),)
            try:
                await repository.abort_rebuild(run_id=run_id)
            except Exception as abort_exc:
                failure_errors = (
                    *failure_errors,
                    _operation_failure("adapter_abort_failed", abort_exc),
                )
            return ObsidianGraphProjectionRebuildReport(
                status="failed",
                graph_read_model=self._config.graph_read_model,
                run_id=run_id,
                scanned=scanned,
                indexed=indexed,
                updated=0,
                skipped=skipped,
                issue_total=len(all_issues),
                issue_counts=issue_counts,
                issues=issues,
                issues_truncated=issues_truncated,
                errors=failure_errors,
                duration_seconds=_duration(started_at, self._monotonic_seconds()),
            )

        return ObsidianGraphProjectionRebuildReport(
            status="completed",
            graph_read_model=self._config.graph_read_model,
            run_id=run_id,
            scanned=scanned,
            indexed=indexed,
            updated=indexed,
            skipped=skipped,
            issue_total=len(all_issues),
            issue_counts=issue_counts,
            issues=issues,
            issues_truncated=issues_truncated,
            duration_seconds=_duration(started_at, self._monotonic_seconds()),
        )

    async def status(self) -> ObsidianGraphProjectionStatusReport:
        """Return status without rebuilding or reading canonical Markdown.

        Returns:
            Typed projection status report.
        """
        if self._config.graph_read_model == "disabled" or self._repository is None:
            return ObsidianGraphProjectionStatusReport(
                status="disabled",
                graph_read_model=self._config.graph_read_model,
                enabled=False,
                node_count=0,
                edge_count=0,
                errors=(),
            )
        try:
            state = await self._repository.state()
        except Exception as exc:
            return ObsidianGraphProjectionStatusReport(
                status="unavailable",
                graph_read_model=self._config.graph_read_model,
                enabled=True,
                node_count=0,
                edge_count=0,
                run_id=None,
                projection_version=None,
                errors=(_operation_failure("adapter_status_failed", exc),),
            )
        if not state.initialized:
            return ObsidianGraphProjectionStatusReport(
                status="uninitialized",
                graph_read_model=self._config.graph_read_model,
                enabled=True,
                node_count=0,
                edge_count=0,
                run_id=None,
                projection_version=None,
                errors=(),
            )
        return ObsidianGraphProjectionStatusReport(
            status="ready",
            graph_read_model=self._config.graph_read_model,
            enabled=True,
            node_count=len(state.projection.nodes),
            edge_count=len(state.projection.edges),
            run_id=state.run_id,
            projection_version=state.projection_version,
            last_run_issue_total=state.issue_total,
            last_run_issue_counts=state.issue_counts,
            errors=(),
        )


def _duration(started_at: float, ended_at: float) -> float:
    """Execute duration.

    Args:
        started_at: Started at used by this operation.
        ended_at: Ended at used by this operation.

    Returns:
        float result produced by duration.
    """
    return round(max(0.0, ended_at - started_at), 6)


def _operation_failure(
    code: str,
    exc: Exception,
) -> ObsidianGraphProjectionOperationError:
    """Execute operation failure.

    Args:
        code: Code used by this operation.
        exc: Exception raised by the underlying operation.

    Returns:
        ObsidianGraphProjectionOperationError result produced by operation failure.
    """
    return ObsidianGraphProjectionOperationError(
        code=code,
        detail=f"{type(exc).__name__} while updating optional graph projection",
    )


def _operation_issue(
    issue: ObsidianGraphProjectionIssue,
) -> ObsidianGraphProjectionOperationError:
    """Execute operation issue.

    Args:
        issue: Issue used by this operation.

    Returns:
        ObsidianGraphProjectionOperationError result produced by operation issue.
    """
    return ObsidianGraphProjectionOperationError(
        code=issue.code.value,
        relative_path=issue.relative_path,
        note_id=issue.note_id,
        edge_id=issue.edge_id,
        detail=issue.detail,
    )


def _issue_counts(
    issues: tuple[ObsidianGraphProjectionIssue, ...],
) -> tuple[ObsidianGraphProjectionIssueCount, ...]:
    """Execute issue counts.

    Args:
        issues: Issues used by this operation.

    Returns:
        tuple[ObsidianGraphProjectionIssueCount, ...] result produced by issue counts.
    """
    counts = Counter(issue.code for issue in issues)
    return tuple(
        ObsidianGraphProjectionIssueCount(code=code, count=counts[code])
        for code in sorted(counts, key=lambda item: item.value)
    )
