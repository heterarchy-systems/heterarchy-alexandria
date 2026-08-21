"""PostgreSQL-native operational recovery planning policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.memory.domain.event_enum.context_enums import RagStrategy
from app.operations.application.recovery.planning.recovery_plan_policy import (
    _blocked_reasons,
    _next_actions,
    _steps,
)
from app.operations.domain.entities.recovery_plan import RecoverySourceSnapshot
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)


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

    blocked = _blocked_reasons(readiness, _source())
    steps = _steps(readiness)

    assert blocked == ["postgresql_server_recovery_required"]
    assert [step.code for step in steps] == ["inspect_postgresql_backup_restore"]
    assert all(step.mutates_state is False for step in steps)
    assert _next_actions(
        OperationalReadinessStatus.BLOCKED, blocked, list(readiness.warnings)
    ) == ["restore_postgresql_from_backup"]


def test_fts_failure_rebuilds_only_vault_then_verifies() -> None:
    readiness = _readiness(warnings=("rag_fts_not_healthy",))

    assert [step.code for step in _steps(readiness)] == [
        "snapshot_sources",
        "reindex_vault",
        "verify_readiness",
    ]


def test_vector_failure_rebuilds_only_embeddings_then_verifies() -> None:
    readiness = _readiness(warnings=("rag_vector_not_healthy",))

    assert [step.code for step in _steps(readiness)] == [
        "snapshot_sources",
        "reindex_embeddings",
        "verify_readiness",
    ]


def test_combined_search_failure_rebuilds_each_required_projection_once() -> None:
    readiness = _readiness(
        warnings=("rag_fts_not_healthy", "rag_embedding_reindex_required")
    )

    assert [step.code for step in _steps(readiness)] == [
        "snapshot_sources",
        "reindex_vault",
        "reindex_embeddings",
        "verify_readiness",
    ]


def test_reconciliation_only_issue_never_rebuilds_storage() -> None:
    readiness = _readiness(warnings=("memory_reconciliation_open_conflicts",))

    steps = _steps(readiness)

    assert [step.code for step in steps] == ["inspect_memory_reconciliation"]
    assert all(step.mutates_state is False for step in steps)


def test_vault_source_failures_block_automatic_recovery() -> None:
    readiness = _readiness(vault_exists=False, root_exists=False)

    assert _blocked_reasons(readiness, _source(count=0)) == [
        "vault_not_found",
        "alexandria_root_not_found",
        "managed_markdown_not_found",
    ]
    assert _blocked_reasons(
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
