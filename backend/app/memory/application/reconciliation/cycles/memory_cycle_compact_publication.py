"""Publish a cycle Compact after verifying its canonical source evidence."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.cycles.memory_cycle_hashing import (
    compact_source_hashes_match,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleCompactChange,
    MemoryCyclePhase,
    MemoryCycleSourceSnapshot,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCyclePhaseStatus
from app.shared.compute.native_text_hashing import hash_text


class MemoryCycleCompactPublication:
    """Verify and publish the Compact created by the cycle coordinator."""

    def __init__(self, compact_service: MemoryCompactService) -> None:
        """Borrow the existing Compact lifecycle owner.

        Args:
            compact_service: Memory Compact application service dependency.
        """
        self._compact_service = compact_service

    async def verify_and_publish(
        self,
        compact: MemoryCompact,
        compact_change: MemoryCycleCompactChange,
        sources: tuple[MemoryCycleSourceSnapshot, ...],
        project: str | None,
    ) -> tuple[MemoryCycleCompactChange, MemoryCyclePhase]:
        """Verify source hashes and CURRENT cardinality before reporting success.

        Args:
            compact: Created draft Memory Compact to verify and publish.
            compact_change: Planned compact change metadata.
            sources: Post-apply canonical source revision snapshots.
            project: Project scope for CURRENT compact cardinality verification.

        Returns:
            Tuple of updated MemoryCycleCompactChange and compact phase outcome.

        Raises:
            RuntimeError: If source hash readback or CURRENT cardinality fails.
        """
        if compact_change.safe_to_publish:
            if not compact_source_hashes_match(compact, sources):
                raise RuntimeError(
                    "Memory Compact source hash readback verification failed"
                )
            current = await self._compact_service.mark_current(compact.id)
            current_compacts, _ = await self._compact_service.list_compacts(
                project=project,
                status=MemoryCompactStatus.CURRENT,
                limit=100,
                offset=0,
            )
            if len(current_compacts) != 1 or current_compacts[0].id != current.id:
                raise RuntimeError(
                    "Memory Compact CURRENT cardinality/readback verification failed"
                )
            compact_change = replace(
                compact_change,
                status=MemoryCompactStatus.CURRENT,
                review_verdict=current.review_verdict,
                content_hash=hash_text(current.markdown_body),
            )
            phase = MemoryCyclePhase(
                name="compact",
                status=MemoryCyclePhaseStatus.SUCCEEDED,
                detail=f"current_compact={current.id}",
            )
        else:
            phase = MemoryCyclePhase(
                name="compact",
                status=MemoryCyclePhaseStatus.REVIEW_REQUIRED,
                detail=f"draft_compact={compact.id}",
                warnings=compact_change.warnings,
            )
        return compact_change, phase
