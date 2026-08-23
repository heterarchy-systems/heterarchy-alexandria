"""Typer commands for Memory Steward readiness and compact freshness workflows."""

from __future__ import annotations

import typer

from app.cli.maintenance_command_context import build_maintenance_gateway
from app.cli.mcp_server_commands import _mcp_smoke_tools
from app.cli.output import run_json_command
from app.cli.type_validate.command_options import (
    DEFAULT_REQUIRED_MCP_TOOLS,
    ApplyOption,
    CoveredToOption,
    ForceOption,
    ForceRefreshOption,
    MaxCompactAgeDaysOption,
    MemoryCompactRefreshOptions,
    MemoryStewardReadinessOptions,
    ProjectOption,
    RefreshCompactOption,
    SummaryOption,
)
from app.cli.type_validate.maintenance_payload_schemas import MaintenanceCheckPayload
from app.cli.type_validate.maintenance_payload_views import (
    check_ok,
    check_summary,
    preflight_ready,
)
from app.mcp_server.backend_api_client import AlexandriaApiSettings
from app.shared.types.extra_types import JSONValue


def register_memory_steward_commands(app: typer.Typer) -> None:
    """Register Memory Steward readiness commands on the parent Typer app.

    Args:
        app: Parent Memory Steward Typer app.
    """
    app.command("readiness")(_readiness)
    app.command("refresh-current-compact")(_refresh_current_compact)
    app.command("preflight")(_preflight)
    app.command("check")(_check)


def _readiness(
    project: ProjectOption = None,
    max_compact_age_days: MaxCompactAgeDaysOption = 30,
) -> int:
    """Check Memory Steward readiness.

    Args:
        project: Project used by this operation.
        max_compact_age_days: Max compact age days used by this operation.

    Returns:
        int result produced by readiness.
    """
    options = MemoryStewardReadinessOptions(
        project=project,
        max_compact_age_days=max_compact_age_days,
    )

    async def operation() -> JSONValue:
        """Execute operation.

        Returns:
            JSONValue result produced by operation.
        """
        return await build_maintenance_gateway().readiness(options)

    exit_code = run_json_command(operation, error_prefix="Alexandria API error")
    return exit_code


def _refresh_current_compact(
    project: ProjectOption = None,
    max_compact_age_days: MaxCompactAgeDaysOption = 30,
    apply: ApplyOption = False,
    force: ForceOption = False,
    covered_to: CoveredToOption = None,
) -> int:
    """Plan or apply a CURRENT Memory Compact refresh.

    Args:
        project: Project used by this operation.
        max_compact_age_days: Max compact age days used by this operation.
        apply: Apply used by this operation.
        force: Whether to force the operation instead of using current state.
        covered_to: Covered to used by this operation.

    Returns:
        int result produced by refresh current compact.
    """
    options = MemoryCompactRefreshOptions(
        project=project,
        max_compact_age_days=max_compact_age_days,
        apply=apply,
        force=force,
        covered_to=covered_to,
    )

    async def operation() -> JSONValue:
        """Execute operation.

        Returns:
            JSONValue result produced by operation.
        """
        return await build_maintenance_gateway().refresh_current_compact(options)

    exit_code = run_json_command(operation, error_prefix="Alexandria API error")
    return exit_code


def _preflight(
    project: ProjectOption = None,
    max_compact_age_days: MaxCompactAgeDaysOption = 30,
    refresh_compact: RefreshCompactOption = False,
    force_refresh: ForceRefreshOption = False,
    covered_to: CoveredToOption = None,
) -> int:
    """Check Memory Steward readiness and fail non-zero when attention is needed.

    Args:
        project: Project used by this operation.
        max_compact_age_days: Max compact age days used by this operation.
        refresh_compact: Refresh compact used by this operation.
        force_refresh: Force refresh used by this operation.
        covered_to: Covered to used by this operation.

    Returns:
        int result produced by preflight.
    """
    options = MemoryCompactRefreshOptions(
        project=project,
        max_compact_age_days=max_compact_age_days,
        apply=refresh_compact,
        force=force_refresh,
        covered_to=covered_to,
    )

    async def operation() -> JSONValue:
        """Execute operation.

        Returns:
            JSONValue result produced by operation.
        """
        return await build_maintenance_gateway().refresh_current_compact(options)

    exit_code = run_json_command(
        operation,
        error_prefix="Alexandria API error",
        attention_required=lambda payload: not preflight_ready(payload),
    )
    return exit_code


def _check(
    project: ProjectOption = None,
    max_compact_age_days: MaxCompactAgeDaysOption = 30,
    refresh_compact: RefreshCompactOption = False,
    force_refresh: ForceRefreshOption = False,
    covered_to: CoveredToOption = None,
    summary: SummaryOption = False,
) -> int:
    """Run MCP tool smoke and Memory Steward preflight as one JSON check.

    Args:
        project: Project used by this operation.
        max_compact_age_days: Max compact age days used by this operation.
        refresh_compact: Refresh compact used by this operation.
        force_refresh: Force refresh used by this operation.
        covered_to: Covered to used by this operation.
        summary: Summary used by this operation.

    Returns:
        int result produced by check.
    """
    options = MemoryCompactRefreshOptions(
        project=project,
        max_compact_age_days=max_compact_age_days,
        apply=refresh_compact,
        force=force_refresh,
        covered_to=covered_to,
    )

    async def operation() -> JSONValue:
        """Execute operation.

        Returns:
            JSONValue result produced by operation.
        """
        mcp_smoke = await _mcp_smoke_tools(
            settings=AlexandriaApiSettings.from_env(),
            mcp_url=None,
            required_tools=DEFAULT_REQUIRED_MCP_TOOLS,
        )
        preflight_payload = await build_maintenance_gateway().refresh_current_compact(
            options
        )
        if summary:
            return check_summary(mcp_smoke, preflight_payload)
        check_payload = MaintenanceCheckPayload(
            ok=check_ok(check_summary(mcp_smoke, preflight_payload)),
            mcp_smoke=mcp_smoke,
            preflight=preflight_payload,
        )
        return check_payload.model_dump(mode="json")

    exit_code = run_json_command(
        operation,
        error_prefix="Alexandria API error",
        attention_required=lambda payload: not check_ok(payload),
    )
    return exit_code
