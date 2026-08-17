"""Typed CLI option and enum contracts for heterarchy-alexandria commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

import typer

from app.mcp_server.type_validate.transport_contracts import McpTransport


class RequiredMcpTool(StrEnum):
    """MCP tools required for Memory Steward and Vault maintenance checks."""

    MEMORY_STEWARD_READINESS = "alexandria_memory_steward_readiness"
    MEMORY_STEWARD_REFRESH_CURRENT_COMPACT = (
        "alexandria_memory_steward_refresh_current_compact"
    )
    VAULT_REVIEW_QUEUE = "alexandria_vault_review_queue"
    VAULT_REVIEW_MOVE_PLAN = "alexandria_vault_review_move_plan"
    VAULT_REVIEW_APPLY_MOVES = "alexandria_vault_review_apply_moves"


DEFAULT_REQUIRED_MCP_TOOLS = tuple(tool.value for tool in RequiredMcpTool)

TransportOption = Annotated[
    McpTransport,
    typer.Option(
        "--transport",
        case_sensitive=True,
        help="MCP transport protocol.",
    ),
]
McpUrlOption = Annotated[
    str | None,
    typer.Option(
        "--mcp-url",
        help="MCP endpoint URL. Defaults to ALEXANDRIA_API_URL + /mcp/.",
    ),
]
RequiredToolOption = Annotated[
    list[str] | None,
    typer.Option(
        "--required-tool",
        help="Required tool name. Defaults to Memory Steward/Vault maintenance tools.",
    ),
]
ProjectOption = Annotated[
    str | None,
    typer.Option(
        "--project", help="Optional project filter, e.g. heterarchy-alexandria."
    ),
]
MaxCompactAgeDaysOption = Annotated[
    int,
    typer.Option(
        "--max-compact-age-days",
        help="Maximum acceptable age for the CURRENT Memory Compact.",
    ),
]
ScopePathOption = Annotated[
    str | None,
    typer.Option("--scope-path", help="Optional vault-relative scope path."),
]
LimitOption = Annotated[
    int,
    typer.Option("--limit", help="Maximum review candidates to return or plan."),
]
SummaryOption = Annotated[
    bool,
    typer.Option("--summary", help="Print only compact machine-readable fields."),
]
RefreshCompactOption = Annotated[
    bool,
    typer.Option(
        "--refresh-compact",
        "--refresh",
        help="Apply CURRENT compact refresh when stale or missing.",
    ),
]
ForceRefreshOption = Annotated[
    bool,
    typer.Option(
        "--force-refresh",
        help="Refresh the compact even when readiness is already fresh.",
    ),
]
CoveredToOption = Annotated[
    str | None,
    typer.Option(
        "--covered-to",
        help="Optional coverage end timestamp for deterministic refreshes.",
    ),
]
ApplyOption = Annotated[
    bool,
    typer.Option(
        "--apply", help="Create the CURRENT compact when refresh is required."
    ),
]
ForceOption = Annotated[
    bool,
    typer.Option(
        "--force",
        help="Create a compact even when readiness is already fresh.",
    ),
]
ReportPathOption = Annotated[
    str | None,
    typer.Option("--report-path", help="Optional vault-relative report path stem."),
]
ConfirmApplyOption = Annotated[
    bool,
    typer.Option(
        "--confirm-apply",
        help="Required when the review move plan contains moves.",
    ),
]
NoReindexOption = Annotated[
    bool,
    typer.Option("--no-reindex", help="Skip Obsidian index rebuild after applying."),
]
VerificationQueryOption = Annotated[
    str | None,
    typer.Option("--verification-query", help="Optional query used after apply."),
]


@dataclass(frozen=True, slots=True)
class MemoryStewardReadinessOptions:
    """Options shared by Memory Steward readiness and compact freshness checks.

    Args:
        project: Optional project filter.
        max_compact_age_days: Maximum acceptable age for CURRENT Memory Compact.
    """

    project: str | None
    max_compact_age_days: int


@dataclass(frozen=True, slots=True)
class VaultReviewOptions:
    """Options shared by vault review queue and move planning commands.

    Args:
        project: Optional project filter.
        scope_path: Optional vault-relative scope path.
        limit: Maximum candidate count to fetch or plan.
    """

    project: str | None
    scope_path: str | None
    limit: int


@dataclass(frozen=True, slots=True)
class MemoryCompactRefreshOptions:
    """Options for commands that plan or apply CURRENT compact refreshes.

    Args:
        project: Optional project filter.
        max_compact_age_days: Maximum acceptable age for CURRENT Memory Compact.
        apply: Whether to create a compact when refresh is required.
        force: Whether to refresh even when current compact is fresh.
        covered_to: Optional deterministic coverage end timestamp.
    """

    project: str | None
    max_compact_age_days: int
    apply: bool
    force: bool
    covered_to: str | None


@dataclass(frozen=True, slots=True)
class VaultReviewApplyOptions:
    """Options for confirmation-gated vault move application.

    Args:
        review: Shared review queue scope and limit options.
        report_path: Optional vault-relative operation report path stem.
        reindex: Whether to rebuild the Obsidian index after applying moves.
        verification_query: Optional query used after apply.
        confirm_apply: Explicit confirmation required for non-empty plans.
    """

    review: VaultReviewOptions
    report_path: str | None
    reindex: bool
    verification_query: str | None
    confirm_apply: bool
