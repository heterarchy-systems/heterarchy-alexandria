"""Typed CLI option and enum contracts for heterarchy-alexandria commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import typer

from app.cli.type_validate.command_option_enums import RequiredMcpTool
from app.mcp_server.type_validate.mcp_transport_enums import McpTransport

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
        help="Required tool name. Defaults to Memory Steward tools.",
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
