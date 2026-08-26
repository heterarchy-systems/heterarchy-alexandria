"""Runtime build and native-extension provenance for operational readiness."""

from __future__ import annotations

from app.operations.domain.entities.operational_runtime_provenance import (
    OperationalRuntimeProvenanceSnapshot,
)
from app.platform.config.app_config import AppConfig
from app.shared.infrastructure.native_compute_extension import (
    load_native_runtime_provenance_module,
)

_EXPECTED_FEATURE_AUTHORITY_SCHEMA_VERSION = 1
_UNKNOWN_REVISION_VALUES = frozenset({"unknown", "unset", "none"})


class OperationalRuntimeProvenanceService:
    """Compare baked runtime identity with deployment and native evidence."""

    def __init__(self, config: AppConfig) -> None:
        """Create the runtime provenance service.

        Args:
            config: Validated application settings boundary.
        """
        self._config = config

    def snapshot(self) -> OperationalRuntimeProvenanceSnapshot:
        """Return current process and native build provenance without mutation.

        Returns:
            Runtime provenance and drift classification for readiness policy.
        """
        runtime_revision = _revision(self._config.runtime_revision)
        expected_revision = _revision(self._config.runtime_expected_revision)
        warnings: list[str] = []
        drift_detected = False

        if expected_revision is None:
            warnings.append(
                "runtime_provenance_unverified"
                if self._config.app_env == "local"
                else "runtime_expected_revision_missing"
            )
        if runtime_revision is None:
            warnings.append(
                "runtime_revision_unverified"
                if self._config.app_env == "local"
                else "runtime_revision_missing"
            )
        if (
            runtime_revision is not None
            and expected_revision is not None
            and runtime_revision != expected_revision
        ):
            drift_detected = True
            warnings.append("runtime_revision_mismatch")

        native_revision: str | None = None
        native_package_version: str | None = None
        native_build_profile: str | None = None
        native_contract_version: int | None = None
        feature_authority_schema_version: int | None = None
        native_aligned = False
        try:
            native = load_native_runtime_provenance_module()
            native_revision = _revision(native.native_git_revision())
            native_package_version = native.native_package_version()
            native_build_profile = native.native_build_profile()
            native_contract_version = native.compute_contract_version()
            feature_authority_schema_version = native.feature_authority_schema_version()
        except RuntimeError:
            warnings.append("native_provenance_unavailable")
        else:
            native_aligned = _native_aligned(runtime_revision, native_revision)
            if runtime_revision is not None and native_revision is None:
                warnings.append(
                    "native_revision_unverified"
                    if self._config.app_env == "local"
                    else "native_revision_missing"
                )
            elif not native_aligned:
                warnings.append("native_revision_mismatch")
            if (
                feature_authority_schema_version
                != _EXPECTED_FEATURE_AUTHORITY_SCHEMA_VERSION
            ):
                native_aligned = False
                warnings.append("native_feature_authority_schema_mismatch")

        verified = (
            runtime_revision is not None
            and expected_revision is not None
            and runtime_revision == expected_revision
            and native_aligned
        )
        return OperationalRuntimeProvenanceSnapshot(
            checked=True,
            environment=self._config.app_env,
            runtime_revision=runtime_revision,
            expected_revision=expected_revision,
            build_timestamp=_text(self._config.runtime_build_timestamp),
            native_revision=native_revision,
            native_package_version=_text(native_package_version),
            native_build_profile=_text(native_build_profile),
            native_contract_version=native_contract_version,
            feature_authority_schema_version=feature_authority_schema_version,
            verified=verified,
            drift_detected=drift_detected,
            native_aligned=native_aligned,
            warnings=tuple(dict.fromkeys(warnings)),
        )


def _native_aligned(runtime_revision: str | None, native_revision: str | None) -> bool:
    """Return whether native revision evidence matches the runtime image.

    Args:
        runtime_revision: Normalized Python runtime source revision.
        native_revision: Normalized Rust extension source revision.

    Returns:
        True when both revisions are present and equal.
    """
    if runtime_revision is None:
        return native_revision is None
    return native_revision == runtime_revision


def _revision(value: str | None) -> str | None:
    """Normalize optional runtime revision metadata.

    Args:
        value: Raw optional revision text.

    Returns:
        Lowercase non-empty revision text, or None when unavailable.
    """
    normalized = _text(value)
    if normalized is None or normalized.casefold() in _UNKNOWN_REVISION_VALUES:
        return None
    return normalized


def _text(value: str | None) -> str | None:
    """Normalize optional build metadata text.

    Args:
        value: Raw optional build metadata.

    Returns:
        Trimmed non-empty text, or None when unavailable.
    """
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
