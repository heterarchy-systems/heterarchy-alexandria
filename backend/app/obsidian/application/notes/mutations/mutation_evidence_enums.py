"""Stable evidence codes used by note mutation recovery outcomes."""

from __future__ import annotations

from enum import StrEnum


class MutationEvidenceCode(StrEnum):
    """Machine-readable evidence attached to mutation outcome records."""

    CAS_TARGET_UNCHANGED = "cas_target_unchanged"
    CHECKPOINT_ABSENT = "checkpoint_absent"
    CHECKPOINT_UNREADABLE_REQUIRES_RECOVERY = "checkpoint_unreadable_requires_recovery"
    COMPLETED_SOURCE_DRIFT = "completed_source_drift"
    COMPLETED_SOURCE_MISSING_OR_REPLACED = "completed_source_missing_or_replaced"
    DURABLE_CHECKPOINT_READBACK_VERIFIED = "durable_checkpoint_readback_verified"
    EFFECT_NOT_STARTED = "effect_not_started"
    EXACT_SOURCE_MATCHES_INTENT = "exact_source_matches_intent"
    EXACT_SOURCE_UNCHANGED = "exact_source_unchanged"
    IDENTITY_DRIFT = "identity_drift"
    NO_RELATE_FENCE_RECORDED = "no_relate_fence_recorded"
    OUTCOME_NOT_ATTRIBUTABLE = "outcome_not_attributable"
    PRIMARY_SOURCE_COMMITTED = "primary_source_committed"
    PROJECTION_STATUS_IS_SEPARATE = "projection_status_is_separate"
    READBACK_FAILED = "readback_failed"
    RECORDED_CONTENT_NOT_CONFIRMED = "recorded_content_not_confirmed"
    RECORDED_CONTENT_READBACK_VERIFIED = "recorded_content_readback_verified"
    RECORDED_NOTE_MISSING = "recorded_note_missing"
    RECORDED_OUTCOME_REQUIRES_RECOVERY = "recorded_outcome_requires_recovery"
    RECORDED_RELATION_ABSENT = "recorded_relation_absent"
    RELATION_READBACK_VERIFIED = "relation_readback_verified"
    SOURCE_CHANGED_SINCE_ADMISSION = "source_changed_since_admission"
    SOURCE_HASH_READBACK_FAILED = "source_hash_readback_failed"
    SOURCE_IDENTITY_CHANGED = "source_identity_changed"
    STARTED_SOURCE_ABSENT = "started_source_absent"
    TARGET_PATH_ABSENT = "target_path_absent"
    WRITE_NOT_STARTED = "write_not_started"
