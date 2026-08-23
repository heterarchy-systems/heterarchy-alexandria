"""Typer commands for vault review queue and safe move workflows."""

from __future__ import annotations

import typer

from app.cli.maintenance_command_context import build_maintenance_gateway
from app.cli.output import run_json_command
from app.cli.type_validate.command_options import (
    ConfirmApplyOption,
    LimitOption,
    NoReindexOption,
    ProjectOption,
    ReportPathOption,
    ScopePathOption,
    SummaryOption,
    VaultReviewApplyOptions,
    VaultReviewOptions,
    VerificationQueryOption,
)
from app.cli.type_validate.maintenance_payload_views import (
    confirmation_required,
    review_queue_summary,
)
from app.shared.types.extra_types import JSONValue


def register_vault_maintenance_commands(app: typer.Typer) -> None:
    """Register vault review commands on the parent Typer app.

    Args:
        app: Parent Vault Typer app.
    """
    app.command("review-queue")(_review_queue)
    app.command("review-move-plan")(_review_move_plan)
    app.command("review-apply-moves")(_review_apply_moves)


def _review_queue(
    project: ProjectOption = None,
    scope_path: ScopePathOption = None,
    limit: LimitOption = 20,
    summary: SummaryOption = False,
) -> int:
    """List notes waiting for vault curation.

    Args:
        project: Project used by this operation.
        scope_path: Scope path used by this operation.
        limit: Maximum number of items to process or return.
        summary: Summary used by this operation.

    Returns:
        int result produced by review queue.
    """
    options = VaultReviewOptions(project=project, scope_path=scope_path, limit=limit)

    async def operation() -> JSONValue:
        """Execute operation.

        Returns:
            JSONValue result produced by operation.
        """
        payload = await build_maintenance_gateway().review_queue(options)
        if summary:
            return review_queue_summary(payload)
        return payload

    exit_code = run_json_command(operation, error_prefix="Alexandria API error")
    return exit_code


def _review_move_plan(
    project: ProjectOption = None,
    scope_path: ScopePathOption = None,
    limit: LimitOption = 20,
) -> int:
    """Build a dry-run safe move plan from review queue candidates.

    Args:
        project: Project used by this operation.
        scope_path: Scope path used by this operation.
        limit: Maximum number of items to process or return.

    Returns:
        int result produced by review move plan.
    """
    options = VaultReviewOptions(project=project, scope_path=scope_path, limit=limit)

    async def operation() -> JSONValue:
        """Execute operation.

        Returns:
            JSONValue result produced by operation.
        """
        return await build_maintenance_gateway().review_move_plan(options)

    exit_code = run_json_command(operation, error_prefix="Alexandria API error")
    return exit_code


def _review_apply_moves(
    project: ProjectOption = None,
    scope_path: ScopePathOption = None,
    limit: LimitOption = 20,
    report_path: ReportPathOption = None,
    confirm_apply: ConfirmApplyOption = False,
    no_reindex: NoReindexOption = False,
    verification_query: VerificationQueryOption = None,
) -> int:
    """Apply safe moves from review queue candidates and write a report.

    Args:
        project: Project used by this operation.
        scope_path: Scope path used by this operation.
        limit: Maximum number of items to process or return.
        report_path: Report path used by this operation.
        confirm_apply: Confirm apply used by this operation.
        no_reindex: No reindex used by this operation.
        verification_query: Verification query used by this operation.

    Returns:
        int result produced by review apply moves.
    """
    options = VaultReviewApplyOptions(
        review=VaultReviewOptions(
            project=project,
            scope_path=scope_path,
            limit=limit,
        ),
        report_path=report_path,
        reindex=not no_reindex,
        verification_query=verification_query,
        confirm_apply=confirm_apply,
    )

    async def operation() -> JSONValue:
        """Execute operation.

        Returns:
            JSONValue result produced by operation.
        """
        return await build_maintenance_gateway().review_apply_moves(options)

    exit_code = run_json_command(
        operation,
        error_prefix="Alexandria API error",
        attention_required=confirmation_required,
    )
    return exit_code
