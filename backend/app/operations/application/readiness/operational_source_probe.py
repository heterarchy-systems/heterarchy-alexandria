"""Bounded source-directory probe and unknown RAG health fallback for readiness."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from functools import partial

import anyio
import anyio.to_thread

from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianReadinessPort,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianVaultLocation,
    ObsidianVaultStatus,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    resolve_vault_path,
)
from app.operations.application.readiness.policy.operational_subsystem_snapshots import (
    vault_snapshot,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalVaultSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessWarningCode,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianDomainError


@dataclass(frozen=True, slots=True)
class SourceProbe:
    """Bounded source-directory availability evidence."""

    exists: bool
    root_exists: bool
    readable: bool
    warning: str | None = None


def vault_snapshot_from_probe(
    location: ObsidianVaultLocation,
    probe: SourceProbe,
) -> OperationalVaultSnapshot:
    """Build source evidence with unknown metadata counts.

    Args:
        location: Configured Obsidian vault location.
        probe: Bounded source-directory availability probe result.

    Returns:
        Vault snapshot with unknown metadata counts.
    """
    return OperationalVaultSnapshot(
        exists=probe.exists,
        readable=probe.readable,
        vault_path=location.vault_path,
        alexandria_root=location.alexandria_root,
        alexandria_root_exists=probe.root_exists,
        indexed_notes=None,
        stale_notes=None,
        error_notes=None,
    )


async def probe_vault_source(
    obsidian_service: ObsidianReadinessPort,
    vault_status: ObsidianVaultStatus | None,
) -> tuple[OperationalVaultSnapshot, tuple[ObsidianIndexError, ...], str | None]:
    """Probe the configured vault source directory and build a vault snapshot.

    Args:
        obsidian_service: Obsidian readiness port providing vault location.
        vault_status: Optional indexed vault status when reachable.

    Returns:
        Tuple of vault snapshot, index errors, and optional source warning code.
    """
    if vault_status is None:
        try:
            source_location = obsidian_service.vault_location()
        except ObsidianDomainError, OSError, ValueError:
            source_probe = SourceProbe(
                exists=False,
                root_exists=False,
                readable=False,
                warning=OperationalReadinessWarningCode.SOURCE_PROBE_UNAVAILABLE.value,
            )
            source_location = ObsidianVaultLocation(vault_path="", alexandria_root=".")
        else:
            source_probe = await probe_source_location(source_location)
        return (
            vault_snapshot_from_probe(source_location, source_probe),
            (),
            source_probe.warning,
        )
    source_location = ObsidianVaultLocation(
        vault_path=vault_status.vault_path,
        alexandria_root=vault_status.alexandria_root,
    )
    source_probe = await probe_source_location(source_location)
    vault = replace(
        vault_snapshot(vault_status),
        exists=source_probe.exists,
        readable=source_probe.readable,
        alexandria_root_exists=source_probe.root_exists,
    )
    return vault, vault_status.index_errors, source_probe.warning


async def probe_source_location(location: ObsidianVaultLocation) -> SourceProbe:
    """Probe one source directory through the bounded framework worker lane.

    Args:
        location: Configured Obsidian vault location.

    Returns:
        Bounded source-directory availability probe result.
    """
    return await anyio.to_thread.run_sync(
        partial(_probe_source_location_sync, location),
        limiter=anyio.to_thread.current_default_thread_limiter(),
    )


def _probe_source_location_sync(location: ObsidianVaultLocation) -> SourceProbe:
    """Read at most one directory entry to prove source availability.

    Args:
        location: Configured Obsidian vault location.

    Returns:
        Bounded source-directory availability probe result.
    """
    try:
        vault = resolve_vault_path(location.vault_path)
        root = resolve_note_path(vault, location.alexandria_root)
    except ObsidianDomainError, OSError, ValueError:
        return SourceProbe(
            exists=False,
            root_exists=False,
            readable=False,
            warning=OperationalReadinessWarningCode.SOURCE_PATH_INVALID.value,
        )
    if not vault.exists():
        return SourceProbe(
            exists=False,
            root_exists=False,
            readable=False,
            warning=OperationalReadinessWarningCode.SOURCE_UNAVAILABLE.value,
        )
    if not root.exists():
        return SourceProbe(
            exists=True,
            root_exists=False,
            readable=False,
            warning=OperationalReadinessWarningCode.SOURCE_ROOT_UNAVAILABLE.value,
        )
    try:
        with os.scandir(root) as entries:
            next(entries, None)
    except OSError:
        return SourceProbe(
            exists=True,
            root_exists=True,
            readable=False,
            warning=OperationalReadinessWarningCode.SOURCE_UNREADABLE.value,
        )
    return SourceProbe(exists=True, root_exists=True, readable=True)


def unknown_rag_health() -> RagDependencyHealth:
    """Return typed RAG diagnostics without asserting healthy or empty state.

    Returns:
        Degraded RAG dependency health fallback.
    """
    return RagDependencyHealth(
        fts=RagHealthState.DEGRADED,
        vector=RagHealthState.DEGRADED,
        embedding=RagHealthState.DEGRADED,
        default_strategy=RagStrategy.FTS_ONLY,
        model_name="unknown",
        dimensions=0,
        fingerprint=None,
        warnings=(OperationalReadinessWarningCode.RAG_HEALTH_UNAVAILABLE.value,),
    )
