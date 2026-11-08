"""Stable recovery step, blocker, error, and next-action codes."""

from __future__ import annotations

from enum import StrEnum


class RecoveryStepCode(StrEnum):
    """Canonical and legacy recovery plan step codes."""

    SNAPSHOT_SOURCES = "snapshot_sources"
    REPAIR_MANAGED_FRONTMATTER = "REPAIR_MANAGED_FRONTMATTER"
    REPAIR_ERROR_NOTES = "repair_error_notes"
    VAULT_REINDEX = "VAULT_REINDEX"
    REINDEX_VAULT = "reindex_vault"
    EMBEDDING_REINDEX = "EMBEDDING_REINDEX"
    REINDEX_EMBEDDINGS = "reindex_embeddings"
    CURRENT_READINESS_CHECK = "CURRENT_READINESS_CHECK"
    VERIFY_READINESS = "verify_readiness"
    GRAPH_REVALIDATE = "GRAPH_REVALIDATE"
    LINK_REVALIDATE = "LINK_REVALIDATE"
    DLQ_RECONCILE = "DLQ_RECONCILE"
    INSPECT_MEMORY_RECONCILIATION = "inspect_memory_reconciliation"
    INSPECT_POSTGRESQL_BACKUP_RESTORE = "inspect_postgresql_backup_restore"


class RecoveryStepErrorCode(StrEnum):
    """Error codes emitted by ordered recovery step execution."""

    NOTE_REPAIR_FAILED = "NOTE_REPAIR_FAILED"
    NOTE_REPAIR_REQUIRED = "NOTE_REPAIR_REQUIRED"
    VAULT_REINDEX_FAILED = "VAULT_REINDEX_FAILED"
    EMBEDDING_REINDEX_FAILED = "EMBEDDING_REINDEX_FAILED"
    COMPILE_RECEIPT_EVIDENCE_MISSING = "COMPILE_RECEIPT_EVIDENCE_MISSING"
    READINESS_VERIFICATION_FAILED = "READINESS_VERIFICATION_FAILED"
    GRAPH_REVALIDATE_FAILED = "GRAPH_REVALIDATE_FAILED"
    LINK_REVALIDATE_FAILED = "LINK_REVALIDATE_FAILED"
    DLQ_RECONCILE_FAILED = "DLQ_RECONCILE_FAILED"
    DLQ_RECONCILIATION_REQUIRED = "DLQ_RECONCILIATION_REQUIRED"
    UNSUPPORTED_RECOVERY_STEP = "UNSUPPORTED_RECOVERY_STEP"
    RECOVERY_RUN_FAILED = "RECOVERY_RUN_FAILED"
    RECOVERY_PLAN_BLOCKED = "RECOVERY_PLAN_BLOCKED"
    RECOVERY_PLAN_DRIFT = "RECOVERY_PLAN_DRIFT"
    RECOVERY_PLAN_IDEMPOTENCY_CONFLICT = "RECOVERY_PLAN_IDEMPOTENCY_CONFLICT"


class RecoveryPlanBlockerCode(StrEnum):
    """Prerequisite and capability blocker codes emitted during recovery planning."""

    POSTGRESQL_SERVER_RECOVERY_REQUIRED = "postgresql_server_recovery_required"
    MANAGED_MARKDOWN_NOT_FOUND = "managed_markdown_not_found"
    SOURCE_SNAPSHOT_UNREADABLE = "source_snapshot_unreadable"
    EMBEDDING_RECOVERY_UNAVAILABLE = "embedding_recovery_unavailable"
    GRAPH_REBUILD_UNAVAILABLE = "graph_rebuild_unavailable"
    LINK_DIAGNOSTICS_UNAVAILABLE = "link_diagnostics_unavailable"
    DLQ_RECONCILE_UNAVAILABLE = "dlq_reconcile_unavailable"
    CURRENT_COMPACT_READER_UNAVAILABLE = "current_compact_reader_unavailable"


class RecoveryDiagnosisSummaryCode(StrEnum):
    """Summary diagnosis codes emitted during operational recovery planning."""

    POSTGRESQL_DATABASE_UNREACHABLE = "POSTGRESQL_DATABASE_UNREACHABLE"


class RecoveryVerificationWarningCode(StrEnum):
    """Warning and blocker codes emitted during post-recovery readiness verification."""

    REPRESENTATIVE_SEARCH_MISSING = "representative_search_missing"
    SOURCE_MARKDOWN_CHANGED = "source_markdown_changed"
    CURRENT_COMPACT_UNAVAILABLE = "current_compact_unavailable"


class RecoveryNextAction(StrEnum):
    """Operator next-action codes emitted by recovery runs."""

    INSPECT_RECOVERY_RUN = "inspect_recovery_run"
