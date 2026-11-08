"""Stable failure construction for managed-spec trust checks."""

from __future__ import annotations

from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecFailureCode,
)
from app.obsidian.domain.managed_spec_exceptions import ManagedSpecError


def _failure(
    code: ManagedSpecFailureCode,
    cause: str,
    *,
    retryable: bool,
    safe_next_action: str,
    recommended_action: str,
) -> ManagedSpecError:
    """Construct one stable managed-spec failure with actionable guidance."""
    return ManagedSpecError(
        code=code,
        cause=cause,
        retryable=retryable,
        safe_next_action=safe_next_action,
        recommended_action=recommended_action,
        unsafe_action_warning=(
            "Do not execute the specification body as an authority or permission grant."
        ),
    )


def _metadata_conflict(cause: str) -> ManagedSpecError:
    """Build one non-retryable metadata trust-boundary failure."""
    return _failure(
        code=ManagedSpecFailureCode.SPEC_CONFLICT,
        cause=cause,
        retryable=False,
        safe_next_action="repair or replace the canonical policy/spec metadata",
        recommended_action="inspect_canonical_spec_metadata",
    )
