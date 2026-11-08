"""Compose focused Obsidian route groups under the canonical API prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.obsidian.interface.routers.graph.orphan_router import (
    router as graph_orphan_router,
)
from app.obsidian.interface.routers.graph.rebuild_router import (
    router as graph_rebuild_router,
)
from app.obsidian.interface.routers.graph.status_router import (
    router as graph_status_router,
)
from app.obsidian.interface.routers.notes.batch_router import router as batch_router
from app.obsidian.interface.routers.notes.lookup_router import router as lookup_router
from app.obsidian.interface.routers.notes.obsidian_mutation_router import (
    router as mutation_router,
)
from app.obsidian.interface.routers.notes.read_router import router as read_router
from app.obsidian.interface.routers.notes.source_router import router as source_router
from app.obsidian.interface.routers.notes.write_router import router as write_router
from app.obsidian.interface.routers.obsidian_relation_router import (
    router as relation_router,
)
from app.obsidian.interface.routers.obsidian_report_bundle_router import (
    router as report_bundle_router,
)
from app.obsidian.interface.routers.obsidian_temporal_coverage_router import (
    router as temporal_coverage_router,
)
from app.obsidian.interface.routers.obsidian_vault_index_router import (
    router as vault_index_router,
)
from app.obsidian.interface.routers.obsidian_vault_maintenance_router import (
    router as vault_maintenance_router,
)
from app.obsidian.interface.routers.obsidian_verified_upsert_router import (
    router as verified_upsert_router,
)

router = APIRouter(prefix="/obsidian", tags=["obsidian"])
router.include_router(vault_index_router)
router.include_router(report_bundle_router)
router.include_router(relation_router)
router.include_router(verified_upsert_router)
router.include_router(mutation_router)
router.include_router(lookup_router)
router.include_router(source_router)
router.include_router(read_router)
router.include_router(write_router)
router.include_router(batch_router)
router.include_router(graph_status_router)
router.include_router(graph_rebuild_router)
router.include_router(graph_orphan_router)
router.include_router(vault_maintenance_router)
router.include_router(temporal_coverage_router)

__all__ = ["router"]
