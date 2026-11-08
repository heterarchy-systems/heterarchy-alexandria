"""Obsidian graph diagnostics, projection rebuild, and orphan census route groups."""

from __future__ import annotations

from app.obsidian.interface.routers.graph.orphan_router import (
    router as orphan_router,
)
from app.obsidian.interface.routers.graph.rebuild_router import (
    router as rebuild_router,
)
from app.obsidian.interface.routers.graph.status_router import (
    router as status_router,
)

__all__ = (
    "orphan_router",
    "rebuild_router",
    "status_router",
)
