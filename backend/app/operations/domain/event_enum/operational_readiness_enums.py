"""Operational readiness status values."""

from __future__ import annotations

from enum import StrEnum


class CompileReceiptStatus(StrEnum):
    """Necessity and validity of persisted compiler evidence."""

    REQUIRED_AND_PRESENT = "REQUIRED_AND_PRESENT"
    REQUIRED_MISSING = "REQUIRED_MISSING"
    OPTIONAL_PRESENT = "OPTIONAL_PRESENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"
    STALE = "STALE"


class OperationalGraphProjectionStatus(StrEnum):
    """Graph projection readiness status values."""

    READY = "ready"
    UNAVAILABLE = "unavailable"
    UNINITIALIZED = "uninitialized"
    UNKNOWN = "unknown"


class OperationalReadinessStatus(StrEnum):
    """Operational readiness states for knowledge retrieval safety."""

    UNKNOWN = "UNKNOWN"
    READY = "READY"
    DEGRADED_FTS_ONLY = "DEGRADED_FTS_ONLY"
    DEGRADED_RUNTIME_DRIFT = "DEGRADED_RUNTIME_DRIFT"
    DEGRADED_RETRIEVAL_CANARY = "DEGRADED_RETRIEVAL_CANARY"
    DEGRADED_PROJECTION_INTEGRITY = "DEGRADED_PROJECTION_INTEGRITY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    RECOVERING = "RECOVERING"
    VERIFYING = "VERIFYING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class OperationalOverallStatus(StrEnum):
    """Operator-facing synthesis of service readiness and data integrity."""

    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"
    RECOVERING = "RECOVERING"


class OperationalReadinessNextAction(StrEnum):
    """Recommended operator remediation and inspection actions."""

    INSPECT_VAULT_CONFIGURATION = "inspect_vault_configuration"
    REINDEX_VAULT = "reindex_vault"
    REINDEX_EMBEDDINGS = "reindex_embeddings"
    INSPECT_DATABASE = "inspect_database"
    INSPECT_RECOVERY_RUN = "inspect_recovery_run"
    INSPECT_MEMORY_RECONCILIATION_REPOSITORY = (
        "inspect_memory_reconciliation_repository"
    )
    PREVIEW_EXISTING_MEMORY_RECONCILIATION = "preview_existing_memory_reconciliation"
    REVIEW_MEMORY_RECONCILIATION = "review_memory_reconciliation"
    INSPECT_MEMORY_RECONCILIATION_FAILURES = "inspect_memory_reconciliation_failures"
    AUDIT_MEMORY_RECONCILIATION_INTEGRITY = "audit_memory_reconciliation_integrity"
    REBUILD_AND_REDEPLOY_RUNTIME = "rebuild_and_redeploy_runtime"
    INSPECT_RETRIEVAL_CANARY = "inspect_retrieval_canary"
    REFRESH_PROJECTION_INTEGRITY = "refresh_projection_integrity"
    INSPECT_OBSIDIAN_INDEX_ERRORS = "inspect_obsidian_index_errors"
    REVIEW_OBSIDIAN_FRONTMATTER_SECURITY_ERRORS = (
        "review_obsidian_frontmatter_security_errors"
    )
    RESOLVE_DUPLICATE_CONTEXT_IDENTITY = "resolve_duplicate_context_identity"
    INSPECT_OBSIDIAN_PATH_SECURITY = "inspect_obsidian_path_security"
    INSPECT_OBSIDIAN_SOURCE_STORAGE = "inspect_obsidian_source_storage"
    INSPECT_OBSIDIAN_INDEX_STORAGE = "inspect_obsidian_index_storage"
    PLAN_INDEX_ERROR_REPAIRS = "plan_index_error_repairs"
    ALEXANDRIA_GRAPH_LIST_ISSUES = "alexandria_graph_list_issues"
    RESTORE_POSTGRESQL_FROM_BACKUP = "restore_postgresql_from_backup"
    RESOLVE_RECOVERY_BLOCKERS = "resolve_recovery_blockers"
    START_RECOVERY_RUN = "start_recovery_run"
    NO_RECOVERY_REQUIRED = "no_recovery_required"


class OperationalReadinessWarningCode(StrEnum):
    """Diagnostic warning and blocker codes emitted during readiness probing."""

    METADATA_INDEX_UNAVAILABLE = "metadata_index_unavailable"
    METADATA_INDEX_SKIPPED_DATABASE_UNAVAILABLE = (
        "metadata_index_skipped_database_unavailable"
    )
    SOURCE_PROBE_UNAVAILABLE = "source_probe_unavailable"
    SOURCE_PATH_INVALID = "source_path_invalid"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_ROOT_UNAVAILABLE = "source_root_unavailable"
    SOURCE_UNREADABLE = "source_unreadable"
    RAG_HEALTH_UNAVAILABLE = "rag_health_unavailable"
    RAG_HEALTH_SKIPPED_DATABASE_UNAVAILABLE = "rag_health_skipped_database_unavailable"
    RUNTIME_PROVENANCE_UNAVAILABLE = "runtime_provenance_unavailable"
    RETRIEVAL_CANARY_UNAVAILABLE = "retrieval_canary_unavailable"
    RETRIEVAL_CANARY_SKIPPED_DATABASE_UNAVAILABLE = (
        "retrieval_canary_skipped_database_unavailable"
    )
    PROJECTION_INTEGRITY_UNAVAILABLE = "projection_integrity_unavailable"
    PROJECTION_INTEGRITY_SKIPPED_DATABASE_UNAVAILABLE = (
        "projection_integrity_skipped_database_unavailable"
    )
    GRAPH_PROJECTION_UNAVAILABLE = "graph_projection_unavailable"
    GRAPH_PROJECTION_SKIPPED_DATABASE_UNAVAILABLE = (
        "graph_projection_skipped_database_unavailable"
    )
    COMPILE_RECEIPT_INVALID = "compile_receipt_invalid"
    COMPILE_RECEIPT_REQUIRED = "compile_receipt_required"
    COMPILE_RECEIPT_STALE = "compile_receipt_stale"
    COMPILE_RECEIPT_OPTIONAL_STALE = "compile_receipt_optional_stale"
    RECOVERY_IN_PROGRESS = "recovery_in_progress"
    GRAPH_PROJECTION_UNCHECKED = "graph_projection_unchecked"
    GRAPH_PROJECTION_STATUS_ERROR = "graph_projection_status_error"
    DATABASE_UNREACHABLE = "database_unreachable"
    DATABASE_INTEGRITY_NOT_HEALTHY = "database_integrity_not_healthy"
    VAULT_NOT_FOUND = "vault_not_found"
    ALEXANDRIA_ROOT_NOT_FOUND = "alexandria_root_not_found"
    OBSIDIAN_STALE_NOTES_PRESENT = "obsidian_stale_notes_present"
    OBSIDIAN_ERROR_NOTES_PRESENT = "obsidian_error_notes_present"
    RAG_FTS_NOT_HEALTHY = "rag_fts_not_healthy"
    RAG_VECTOR_NOT_HEALTHY = "rag_vector_not_healthy"
    RAG_EMBEDDING_REINDEX_REQUIRED = "rag_embedding_reindex_required"
    RAG_EMBEDDING_NOT_HEALTHY = "rag_embedding_not_healthy"
    RAG_DEFAULT_STRATEGY_NOT_HYBRID = "rag_default_strategy_not_hybrid"
    RAG_STATUS_WARNINGS_PRESENT = "rag_status_warnings_present"
    MEMORY_RECONCILIATION_REPOSITORY_UNREACHABLE = (
        "memory_reconciliation_repository_unreachable"
    )
    MEMORY_RECONCILIATION_TEMPORAL_BACKFILL_REQUIRED = (
        "memory_reconciliation_temporal_backfill_required"
    )
    MEMORY_RECONCILIATION_REVIEW_REQUIRED = "memory_reconciliation_review_required"
    MEMORY_RECONCILIATION_OPEN_CONFLICTS = "memory_reconciliation_open_conflicts"
    MEMORY_RECONCILIATION_REVIEWS_IN_PROGRESS = (
        "memory_reconciliation_reviews_in_progress"
    )
    MEMORY_RECONCILIATION_PARTIAL_APPLY_PRESENT = (
        "memory_reconciliation_partial_apply_present"
    )
    MEMORY_RECONCILIATION_FAILED_RESULTS_PRESENT = (
        "memory_reconciliation_failed_results_present"
    )
    MEMORY_RECONCILIATION_HARD_DELETE_DETECTED = (
        "memory_reconciliation_hard_delete_detected"
    )
    RUNTIME_PROVENANCE_UNVERIFIED = "runtime_provenance_unverified"
    RUNTIME_REVISION_UNVERIFIED = "runtime_revision_unverified"
    NATIVE_REVISION_UNVERIFIED = "native_revision_unverified"
    RUNTIME_EXPECTED_REVISION_MISSING = "runtime_expected_revision_missing"
    RUNTIME_REVISION_MISSING = "runtime_revision_missing"
    RUNTIME_REVISION_MISMATCH = "runtime_revision_mismatch"
    NATIVE_PROVENANCE_UNAVAILABLE = "native_provenance_unavailable"
    NATIVE_REVISION_MISSING = "native_revision_missing"
    NATIVE_REVISION_MISMATCH = "native_revision_mismatch"
    NATIVE_FEATURE_AUTHORITY_SCHEMA_MISMATCH = (
        "native_feature_authority_schema_mismatch"
    )
    RETRIEVAL_CANARY_FTS_ONLY_FAILED = "retrieval_canary_fts_only_failed"
    RETRIEVAL_CANARY_VECTOR_ONLY_FAILED = "retrieval_canary_vector_only_failed"
    RETRIEVAL_CANARY_HYBRID_FAILED = "retrieval_canary_hybrid_failed"
    PROJECTION_INTEGRITY_SNAPSHOT_MISSING = "projection_integrity_snapshot_missing"
    PROJECTION_INTEGRITY_SNAPSHOT_STALE = "projection_integrity_snapshot_stale"
    PROJECTION_INTEGRITY_SOURCE_REVISION_MISMATCH = (
        "projection_integrity_source_revision_mismatch"
    )
    PROJECTION_INTEGRITY_INVALID_NOTES = "projection_integrity_invalid_notes"
    MAINTENANCE_DLQ_PRESENT = "maintenance_dlq_present"
    MAINTENANCE_DLQ_UNKNOWN_OUTCOME = "maintenance_dlq_unknown_outcome"
