"""Adapters that reuse report-bundle checkpoints and verified logical writes."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Final

import anyio
from pydantic import TypeAdapter

from app.memory.domain.event_enum.context_enums import ContextSourceType
from app.memory.domain.types.context_payload_types import (
    ContextProvenancePayload,
)
from app.obsidian.application.service.notes.obsidian_verified_upsert_service import (
    ObsidianVerifiedUpsertService,
)
from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecCheckpoint,
    ManagedSpecCheckpointStore,
    ManagedSpecOutputWrite,
    ManagedSpecOutputWriter,
    ManagedSpecOutputWriteResult,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedUpsertRequest,
    ObsidianVerifiedUpsertResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.shared.compute.native_text_hashing import hash_text

_CHECKPOINT_ADAPTER: Final[TypeAdapter[ManagedSpecCheckpoint]] = TypeAdapter(
    ManagedSpecCheckpoint
)
_CHECKPOINT_PREFIX = "managed-spec:"


class ObsidianManagedSpecCheckpointStore(ManagedSpecCheckpointStore):
    """Reuse the existing report-bundle run-store as typed managed-spec state."""

    def __init__(self, run_store: ObsidianReportBundleRunStore) -> None:
        """Initialize the adapter over one existing durable run store."""
        self._run_store = run_store

    async def load(self, idempotency_key: str) -> ManagedSpecCheckpoint | None:
        """Load and validate one managed-spec checkpoint off the event loop."""
        return await _run_blocking(
            partial(
                self._run_store.load_typed,
                _checkpoint_key(idempotency_key),
                _CHECKPOINT_ADAPTER,
            )
        )

    async def save_if_absent(self, checkpoint: ManagedSpecCheckpoint) -> bool:
        """Fence first admission under the caller-owned maintenance lease."""
        existing = await self.load(checkpoint.idempotency_key)
        if existing is not None:
            return False
        await _run_blocking(
            partial(
                self._run_store.save_typed,
                _checkpoint_key(checkpoint.idempotency_key),
                checkpoint,
                _CHECKPOINT_ADAPTER,
            )
        )
        return True

    async def save(self, checkpoint: ManagedSpecCheckpoint) -> None:
        """Durably replace a checkpoint owned by this execution."""
        await _run_blocking(
            partial(
                self._run_store.save_typed,
                _checkpoint_key(checkpoint.idempotency_key),
                checkpoint,
                _CHECKPOINT_ADAPTER,
            )
        )


class ObsidianManagedSpecOutputWriter(ManagedSpecOutputWriter):
    """Adapt managed-spec provenance to the canonical verified-upsert owner."""

    def __init__(self, service: ObsidianVerifiedUpsertService) -> None:
        """Initialize the adapter with the existing verified-upsert service."""
        self._service = service

    async def verified_upsert(
        self,
        request: ManagedSpecOutputWrite,
    ) -> ManagedSpecOutputWriteResult:
        """Persist one logical output through canonical verified-upsert."""
        result = await self._service.upsert(
            ObsidianVerifiedUpsertRequest(
                identity=request.logical_identity,
                title=request.title,
                body=request.body,
                alexandria_type=AlexandriaNoteType.CONTEXT,
                idempotency_key=request.idempotency_key,
                expected_content_hash=request.expected_content_hash,
                provenance=_provenance(request),
                source="mcp",
            )
        )
        return _output_result(result)


def _checkpoint_key(idempotency_key: str) -> str:
    """Namespace managed-spec records inside the shared run-store authority."""
    return _CHECKPOINT_PREFIX + idempotency_key


async def _run_blocking[T](operation: Callable[[], T]) -> T:
    """Run bounded local checkpoint I/O through AnyIO's shared thread lane."""
    return await anyio.to_thread.run_sync(
        operation,
        limiter=anyio.to_thread.current_default_thread_limiter(),
    )


def _provenance(request: ManagedSpecOutputWrite) -> ContextProvenancePayload:
    """Build typed provenance pins for policy/spec revision and envelope."""
    return {
        "source_actor_id": "managed-spec",
        "source_actor_type": ContextSourceType.SYSTEM,
        "source_run_id": f"sha256:{hash_text(request.idempotency_key)}",
        "external_run_id": None,
        "artifact_refs": [
            f"policy:{request.policy_note_id}",
            f"spec:{request.spec_note_id}",
        ],
        "evidence_refs": [
            f"policy-version:{request.policy_version}:sha256:{request.policy_content_hash}",
            f"spec-version:{request.spec_version}:sha256:{request.spec_content_hash}",
            f"managed-spec-envelope:sha256:{request.prepared_envelope_hash}",
        ],
        "confidence": None,
    }


def _output_result(
    result: ObsidianVerifiedUpsertResult,
) -> ManagedSpecOutputWriteResult:
    """Map canonical verified-upsert evidence into managed-spec evidence."""
    return ManagedSpecOutputWriteResult(
        operation=result.operation.value,
        note_id=result.note_id,
        canonical_path=result.canonical_path,
        logical_identity=result.logical_identity,
        content_hash=result.content_hash,
        storage_durable=result.storage_status.value == "verified",
        readback_verified=result.readback_verified,
        metadata_status=result.metadata_status.value,
        fts_status=result.fts_status.value,
        vector_status=result.vector_status.value,
        graph_edge_index_status=result.graph_edge_index_status.value,
        graph_projection_status=result.graph_projection_status.value,
        duplicate_safe=result.duplicate_safety.value == "verified",
        warnings=result.warnings,
    )
