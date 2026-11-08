"""Classify optional and required knowledge compile receipts truthfully."""

from datetime import datetime

from app.operations.domain.entities.operational_readiness import (
    OperationalCompileReceiptSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    CompileReceiptStatus,
    OperationalReadinessWarningCode as _WarnCode,
)
from app.shared.types.extra_types import JSONObject


def compile_receipt_snapshot(
    receipt: JSONObject | None,
    *,
    required: bool = False,
    expected_policy_version: str | None = None,
    expected_plan_fingerprint: str | None = None,
) -> OperationalCompileReceiptSnapshot:
    """Classify persisted evidence without interpreting absence as corruption.

    Args:
        receipt: Canonical compiler receipt, absent when that path was unused.
        required: Whether the consuming path requires compiler evidence.
        expected_policy_version: Current policy fingerprint when known.
        expected_plan_fingerprint: Exact plan fingerprint expected by the
            successful compile path when known.

    Returns:
        Explicit state, source fields, warnings and readiness blockers.
    """
    if receipt is None:
        return OperationalCompileReceiptSnapshot(
            required=required,
            status=CompileReceiptStatus.REQUIRED_MISSING
            if required
            else CompileReceiptStatus.NOT_APPLICABLE,
            blockers=(_WarnCode.COMPILE_RECEIPT_REQUIRED.value,) if required else (),
        )
    applied_at = receipt.get("applied_at")
    fingerprint = receipt.get("plan_fingerprint")
    policy = receipt.get("policy_version")
    counts = [
        receipt.get(name)
        for name in (
            "changed_documents",
            "removed_documents",
            "embedding_invalidated_documents",
            "diagnostic_count",
        )
    ]
    try:
        timestamp = (
            datetime.fromisoformat(applied_at) if isinstance(applied_at, str) else None
        )
    except ValueError:
        timestamp = None
    if (
        timestamp is None
        or timestamp.tzinfo is None
        or timestamp.utcoffset() is None
        or not isinstance(fingerprint, str)
        or not fingerprint
        or not isinstance(policy, str)
        or not policy
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in counts
        )
    ):
        return OperationalCompileReceiptSnapshot(
            available=True,
            required=required,
            status=CompileReceiptStatus.INVALID,
            blockers=(_WarnCode.COMPILE_RECEIPT_INVALID.value,),
        )
    stale = (
        expected_policy_version is not None and policy != expected_policy_version
    ) or (
        expected_plan_fingerprint is not None
        and fingerprint != expected_plan_fingerprint
    )
    return OperationalCompileReceiptSnapshot(
        available=True,
        required=required,
        status=CompileReceiptStatus.STALE
        if stale
        else (
            CompileReceiptStatus.REQUIRED_AND_PRESENT
            if required
            else CompileReceiptStatus.OPTIONAL_PRESENT
        ),
        applied_at=timestamp,
        plan_fingerprint=fingerprint,
        policy_version=policy,
        changed_documents=_count(receipt, "changed_documents"),
        removed_documents=_count(receipt, "removed_documents"),
        embedding_invalidated_documents=_count(
            receipt, "embedding_invalidated_documents"
        ),
        diagnostic_count=_count(receipt, "diagnostic_count"),
        blockers=(_WarnCode.COMPILE_RECEIPT_STALE.value,) if stale and required else (),
        warnings=(_WarnCode.COMPILE_RECEIPT_OPTIONAL_STALE.value,)
        if stale and not required
        else (),
    )


def _count(receipt: JSONObject, name: str) -> int | None:
    """Narrow an already checked receipt counter.

    Args:
        receipt: Validated compile receipt JSON dictionary.
        name: Counter field name in the receipt.

    Returns:
        Integer counter value, or None if not an integer.
    """
    value = receipt[name]
    return value if isinstance(value, int) else None
