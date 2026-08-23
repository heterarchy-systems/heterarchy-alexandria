"""Compose focused Obsidian route groups under the canonical API prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.obsidian.interface.routers.obsidian_graph_projection_router import (
    router as graph_projection_router,
)
from app.obsidian.interface.routers.obsidian_librarian_router import (
    router as librarian_router,
)
from app.obsidian.interface.routers.obsidian_note_router import router as note_router
from app.obsidian.interface.routers.obsidian_vault_index_router import (
    router as vault_index_router,
)

router = APIRouter(prefix="/obsidian", tags=["obsidian"])
router.include_router(vault_index_router)
router.include_router(note_router)
router.include_router(graph_projection_router)
router.include_router(librarian_router)

__all__ = ["router"]
