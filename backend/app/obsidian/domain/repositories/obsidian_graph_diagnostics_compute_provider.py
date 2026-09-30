"""Compute port for deterministic graph diagnostics."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.contracts.obsidian_graph_diagnostics_contracts import (
    ObsidianGraphDiagnosticEdge,
    ObsidianGraphDiagnosticNote,
    ObsidianGraphDiagnosticsResult,
    ObsidianGraphOrphanDiagnosticRequest,
    ObsidianGraphSuggestionDiagnosticRequest,
)


class IObsidianGraphDiagnosticsComputeProvider(ABC):
    """Rust-owned graph debt and relation suggestion compute."""

    @abstractmethod
    def compute(
        self,
        notes: tuple[ObsidianGraphDiagnosticNote, ...],
        edges: tuple[ObsidianGraphDiagnosticEdge, ...],
        orphan_request: ObsidianGraphOrphanDiagnosticRequest | None,
        suggestion_request: ObsidianGraphSuggestionDiagnosticRequest | None,
    ) -> ObsidianGraphDiagnosticsResult:
        """Compute bounded graph diagnostics from Python-loaded source rows."""
