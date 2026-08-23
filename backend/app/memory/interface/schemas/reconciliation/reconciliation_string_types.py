"""Semantic constrained-string aliases for reconciliation boundary schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

type ReconciliationScopeFilterText = Annotated[
    str | None,
    StringConstraints(strict=True, max_length=1000),
]

type ReconciliationTitleText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=2000),
]
