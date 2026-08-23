"""Semantic constrained-string aliases for Obsidian boundary schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

type ObsidianQueryText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1),
]

type ObsidianPathText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1),
]

type ObsidianRepairPlanHash = Annotated[
    str,
    StringConstraints(strict=True, min_length=64, max_length=64),
]
