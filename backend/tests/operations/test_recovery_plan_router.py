"""Recovery plan router contracts."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.interface.routers.recovery_plan_router import recovery_plan
from app.operations.interface.schemas.operations.recovery_plan_schema import (
    RecoveryPlanRequestSchema,
)
from app.shared.infrastructure.database import Database


class _FakeContextService:
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.REINDEX_REQUIRED,
            default_strategy=RagStrategy.FTS_ONLY,
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=("embedding fingerprint mismatch",),
        )


class _FakeObsidianService:
    def __init__(self, vault: Path) -> None:
        self._vault = vault

    async def status(self) -> ObsidianVaultStatus:
        return ObsidianVaultStatus(
            vault_path=str(self._vault),
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=1,
            stale_notes=0,
            error_notes=0,
        )


def test_recovery_plan_route_returns_read_only_plan_payload(tmp_path: Path) -> None:
    """POST handler should expose recovery dry-run plan contract."""

    async def scenario() -> dict[str, object]:
        note = tmp_path / "vault" / "Alexandria" / "note.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Note\n", encoding="utf-8")
        database = Database(database_url=os.environ["DATABASE_URL"])
        response = await recovery_plan(
            request=RecoveryPlanRequestSchema(idempotency_key="route-key"),
            database=database,
            context_service=_FakeContextService(),
            obsidian_service=_FakeObsidianService(tmp_path / "vault"),
            reconciliation_service=None,
            callbacks=None,
        )
        return response.model_dump(mode="json")

    payload = anyio.run(scenario)

    assert payload["status"] == "BLOCKED"
    assert payload["dry_run"] is True
    assert payload["automatic_execution_allowed"] is False
    assert payload["idempotency_key"] == "route-key"
    assert "rag_embedding_reindex_required" in payload["diagnosis"]
    assert "embedding_recovery_unavailable" in payload["blocked_reasons"]
    assert payload["steps"][0]["code"] == "snapshot_sources"
