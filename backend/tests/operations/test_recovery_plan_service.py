"""PostgreSQL-native operational recovery planning policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import anyio
import pytest
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService
from tests.operations.test_operational_readiness_service import (
    _FakeContextService,
    _FakeObsidianService,
    _healthy_rag,
    _HealthyPostgresDatabase,
    _obsidian_status,
)

from app.memory.domain.event_enum.context_enums import RagStrategy
from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.application.recovery.planning.recovery_plan_policy import (
    blocked_reasons,
    bounded_error_note_paths,
    missing_step_capabilities,
    next_actions,
    plan_hash,
    steps as plan_steps,
)
from app.operations.application.recovery.planning.recovery_plan_service import (
    RecoveryPlanService,
)
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlanStep,
    RecoverySourceSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONObject


def _readiness(
    *,
    reachable: bool = True,
    warnings: tuple[str, ...] = (),
    vault_exists: bool = True,
    root_exists: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=(
            OperationalReadinessStatus.READY
            if not warnings and reachable
            else OperationalReadinessStatus.RECOVERY_REQUIRED
        ),
        database=SimpleNamespace(reachable=reachable),
        vault=SimpleNamespace(
            exists=vault_exists,
            alexandria_root_exists=root_exists,
            indexed_notes=3,
        ),
        rag=SimpleNamespace(effective_strategy=RagStrategy.HYBRID),
        graph=SimpleNamespace(status="ready", last_run_issue_total=0),
        warnings=warnings,
    )


def _source(
    *, count: int = 1, access_error: str | None = None
) -> RecoverySourceSnapshot:
    return RecoverySourceSnapshot(
        vault_path="/vault",
        alexandria_root="Alexandria",
        managed_markdown_count=count,
        representative_path="/vault/Alexandria/note.md" if count else None,
        representative_sha256="abc" if count else None,
        disk_free_bytes=1_000_000,
        access_error=access_error,
        markdown_manifest={"Alexandria/note.md": "1:1"} if count else {},
    )


def test_unreachable_postgres_is_blocked_and_requires_external_restore() -> None:
    readiness = _readiness(reachable=False, warnings=("database_unreachable",))

    blocked = blocked_reasons(readiness, _source())
    steps = plan_steps(readiness)

    assert blocked == ["postgresql_server_recovery_required"]
    assert [step.code for step in steps] == ["inspect_postgresql_backup_restore"]
    assert all(step.mutates_state is False for step in steps)
    assert next_actions(
        OperationalReadinessStatus.BLOCKED, blocked, list(readiness.warnings)
    ) == ["restore_postgresql_from_backup"]


def test_fts_failure_rebuilds_vault_and_dependent_graph_then_verifies() -> None:
    readiness = _readiness(warnings=("rag_fts_not_healthy",))

    assert [step.code for step in plan_steps(readiness)] == [
        "snapshot_sources",
        "VAULT_REINDEX",
        "GRAPH_REVALIDATE",
        "LINK_REVALIDATE",
        "CURRENT_READINESS_CHECK",
    ]


def test_vector_failure_rebuilds_only_embeddings_then_verifies() -> None:
    readiness = _readiness(warnings=("rag_vector_not_healthy",))

    assert [step.code for step in plan_steps(readiness)] == [
        "snapshot_sources",
        "EMBEDDING_REINDEX",
        "CURRENT_READINESS_CHECK",
    ]


def test_combined_search_failure_rebuilds_each_required_projection_once() -> None:
    readiness = _readiness(
        warnings=("rag_fts_not_healthy", "rag_embedding_reindex_required")
    )

    assert [step.code for step in plan_steps(readiness)] == [
        "snapshot_sources",
        "VAULT_REINDEX",
        "EMBEDDING_REINDEX",
        "GRAPH_REVALIDATE",
        "LINK_REVALIDATE",
        "CURRENT_READINESS_CHECK",
    ]


def test_reconciliation_only_issue_never_rebuilds_storage() -> None:
    readiness = _readiness(warnings=("memory_reconciliation_open_conflicts",))

    steps = plan_steps(readiness)

    assert [step.code for step in steps] == [
        "inspect_memory_reconciliation",
        "CURRENT_READINESS_CHECK",
    ]
    assert all(step.mutates_state is False for step in steps)


def test_vault_source_failures_block_automatic_recovery() -> None:
    readiness = _readiness(vault_exists=False, root_exists=False)

    assert blocked_reasons(readiness, _source(count=0)) == [
        "vault_not_found",
        "alexandria_root_not_found",
        "managed_markdown_not_found",
    ]
    assert blocked_reasons(
        readiness, _source(access_error="source_snapshot_unreadable")
    ) == [
        "source_snapshot_unreadable",
        "vault_not_found",
        "alexandria_root_not_found",
    ]


def test_source_snapshot_uses_lightweight_inventory_tokens() -> None:
    snapshot = _source()

    assert snapshot.markdown_manifest == {"Alexandria/note.md": "1:1"}
    assert snapshot.representative_sha256 == "abc"
    assert datetime.now(UTC).tzinfo is not None


def test_error_notes_plan_bounded_note_local_repair_without_broad_reindex() -> None:
    """Index-error notes get one bounded repair lane, never a broad reindex."""
    readiness = _readiness(warnings=("obsidian_error_notes_present",))

    steps = plan_steps(
        readiness, error_note_paths=["Alexandria/A.md", "Alexandria/B.md"]
    )

    assert [step.code for step in steps] == [
        "snapshot_sources",
        "REPAIR_MANAGED_FRONTMATTER",
        "CURRENT_READINESS_CHECK",
    ]
    assert [step.mutates_state for step in steps] == [False, True, False]
    assert next_actions(readiness.status, [], list(readiness.warnings)) == [
        "start_recovery_run"
    ]


def test_error_notes_with_stale_embeddings_repair_before_embedding_rebuild() -> None:
    """Note-local repairs run before the embedding lane in planned order."""
    readiness = _readiness(
        warnings=("obsidian_error_notes_present", "rag_vector_not_healthy")
    )

    steps = plan_steps(readiness, error_note_paths=["Alexandria/A.md"])

    assert [step.code for step in steps] == [
        "snapshot_sources",
        "REPAIR_MANAGED_FRONTMATTER",
        "EMBEDDING_REINDEX",
        "CURRENT_READINESS_CHECK",
    ]


def test_stale_notes_still_plan_vault_reindex() -> None:
    """Stale notes keep the existing broad reindex lane."""
    readiness = _readiness(warnings=("obsidian_stale_notes_present",))

    assert [step.code for step in plan_steps(readiness)] == [
        "snapshot_sources",
        "VAULT_REINDEX",
        "GRAPH_REVALIDATE",
        "LINK_REVALIDATE",
        "CURRENT_READINESS_CHECK",
    ]
    assert next_actions(readiness.status, [], list(readiness.warnings)) == [
        "start_recovery_run"
    ]


def test_error_note_paths_are_bounded_and_deduplicated() -> None:
    """The bounded repair list caps and deduplicates planned note repairs."""
    bounded = bounded_error_note_paths(
        ["Alexandria/A.md", "Alexandria/A.md", *(f"P{i}.md" for i in range(60))]
    )

    assert len(bounded) == 50
    assert bounded[0] == "Alexandria/A.md"
    assert len(set(bounded)) == len(bounded)


def test_plan_hash_binds_steps_diagnosis_and_source_manifest() -> None:
    """The plan hash changes with steps, diagnosis, or source manifest drift."""
    readiness = _readiness(warnings=("rag_fts_not_healthy",))
    steps = plan_steps(readiness)
    diagnosis = ["rag_fts_not_healthy"]

    base = plan_hash(steps, diagnosis, _source())
    same = plan_hash(steps, diagnosis, _source())
    drifted_manifest = RecoverySourceSnapshot(
        vault_path="/vault",
        alexandria_root="Alexandria",
        managed_markdown_count=1,
        representative_path="/vault/Alexandria/note.md",
        representative_sha256="abc",
        disk_free_bytes=1_000_000,
        markdown_manifest={"Alexandria/note.md": "2:9"},
    )
    other = plan_hash(steps, diagnosis, drifted_manifest)
    other_steps = plan_steps(
        _readiness(warnings=("rag_vector_not_healthy",)),
        error_note_paths=["X.md"],
    )

    assert base == same
    assert base != other
    assert base != plan_hash(other_steps, diagnosis, _source())
    assert base != plan_hash(steps, ["changed"], _source())
    manifest_ab = RecoverySourceSnapshot(
        vault_path="/vault",
        alexandria_root="Alexandria",
        managed_markdown_count=2,
        representative_path="/vault/Alexandria/a.md",
        representative_sha256="abc",
        disk_free_bytes=1_000_000,
        markdown_manifest={"Alexandria/a.md": "1:1", "Alexandria/b.md": "2:2"},
    )
    manifest_ba = RecoverySourceSnapshot(
        vault_path="/vault",
        alexandria_root="Alexandria",
        managed_markdown_count=2,
        representative_path="/vault/Alexandria/a.md",
        representative_sha256="abc",
        disk_free_bytes=1_000_000,
        markdown_manifest={"Alexandria/b.md": "2:2", "Alexandria/a.md": "1:1"},
    )
    assert plan_hash(steps, diagnosis, manifest_ab) == plan_hash(
        steps, diagnosis, manifest_ba
    )


def test_missing_cause_specific_callbacks_block_recovery_instead_of_no_op() -> None:
    steps = [
        RecoveryPlanStep("EMBEDDING_REINDEX", "Embeddings", True),
        RecoveryPlanStep("GRAPH_REVALIDATE", "Graph", True),
        RecoveryPlanStep("LINK_REVALIDATE", "Links", False),
        RecoveryPlanStep("DLQ_RECONCILE", "DLQ", False),
    ]

    assert missing_step_capabilities(
        steps,
        embedding_recovery_available=False,
        graph_rebuild_available=False,
        link_diagnostics_available=False,
        dlq_reconcile_available=False,
        current_compact_reader_available=False,
    ) == [
        "embedding_recovery_unavailable",
        "graph_rebuild_unavailable",
        "link_diagnostics_unavailable",
        "dlq_reconcile_unavailable",
    ]


def test_composed_healthy_plan_is_a_real_noop_with_readiness_check(
    tmp_path,
) -> None:
    """A composed healthy plan has no repair effects and remains executable."""
    status = _obsidian_status(tmp_path)
    note = tmp_path / "vault" / "Alexandria" / "Contexts" / "healthy.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\nid: healthy\n---\n# Healthy\n", encoding="utf-8")
    database = _HealthyPostgresDatabase()
    database.is_postgresql = True
    service = RecoveryPlanService(
        database=cast(Database, database),
        context_service=_FakeContextService(_healthy_rag()),
        obsidian_service=_FakeObsidianService(status),
        graph_projection_service=HealthyGraphProjectionService(),
        current_compact_reader_callback=lambda: _healthy_compact_evidence(),
    )

    plan = anyio.run(
        service.plan,
        RecoveryPlanRequest(idempotency_key="healthy-composed"),
    )

    assert plan.automatic_execution_allowed is True
    assert plan.blocked_reasons == ()
    assert [step.code for step in plan.steps] == [
        "snapshot_sources",
        "CURRENT_READINESS_CHECK",
    ]


async def _healthy_compact_evidence() -> JSONObject:
    """Return independent CURRENT evidence for composed plan tests."""
    return {"available": True, "status": "CURRENT", "count": 1}


def test_composed_embedding_recovery_without_owner_is_blocked(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale embedding cause cannot silently degrade into a fake no-op."""
    status = _obsidian_status(tmp_path)
    note = tmp_path / "vault" / "Alexandria" / "Contexts" / "stale.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\nid: stale\n---\n# Stale\n", encoding="utf-8")
    database = _HealthyPostgresDatabase()
    database.is_postgresql = True
    service = RecoveryPlanService(
        database=cast(Database, database),
        context_service=_FakeContextService(_healthy_rag()),
        obsidian_service=_FakeObsidianService(status),
        graph_projection_service=HealthyGraphProjectionService(),
        current_compact_reader_callback=lambda: _healthy_compact_evidence(),
    )

    # Force the readiness owner to expose the cause while leaving the
    # bounded embedding owner unwired.
    from app.operations.application.readiness.operational_readiness_service import (
        OperationalReadinessService,
    )

    async def fake_snapshot(self):
        del self
        readiness = _readiness(warnings=("rag_embedding_reindex_required",))
        readiness.vault.vault_path = str(tmp_path / "vault")
        readiness.vault.alexandria_root = "Alexandria"
        return readiness

    monkeypatch.setattr(OperationalReadinessService, "snapshot", fake_snapshot)
    plan = anyio.run(
        service.plan,
        RecoveryPlanRequest(idempotency_key="embedding-blocked"),
    )

    assert plan.automatic_execution_allowed is False
    assert "embedding_recovery_unavailable" in plan.blocked_reasons
