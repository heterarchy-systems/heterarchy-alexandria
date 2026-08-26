"""Runtime provenance read models for operational readiness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationalRuntimeProvenanceSnapshot:
    """Build and native-extension identity observed by the running process."""

    checked: bool
    environment: str
    runtime_revision: str | None
    expected_revision: str | None
    build_timestamp: str | None
    native_revision: str | None
    native_package_version: str | None
    native_build_profile: str | None
    native_contract_version: int | None
    feature_authority_schema_version: int | None
    verified: bool
    drift_detected: bool
    native_aligned: bool
    warnings: tuple[str, ...] = ()


def unchecked_runtime_provenance_snapshot() -> OperationalRuntimeProvenanceSnapshot:
    """Return a neutral runtime snapshot for legacy construction boundaries.

    Returns:
        Unchecked runtime-provenance snapshot with no asserted build evidence.
    """
    return OperationalRuntimeProvenanceSnapshot(
        checked=False,
        environment="local",
        runtime_revision=None,
        expected_revision=None,
        build_timestamp=None,
        native_revision=None,
        native_package_version=None,
        native_build_profile=None,
        native_contract_version=None,
        feature_authority_schema_version=None,
        verified=False,
        drift_detected=False,
        native_aligned=False,
        warnings=(),
    )
