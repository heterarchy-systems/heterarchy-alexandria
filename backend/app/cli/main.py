"""Top-level Typer CLI entrypoint for heterarchy-alexandria."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click
import typer
from typer.main import get_command

from app.cli.maintenance_workflow_commands import memory_steward_app, vault_app
from app.cli.mcp_server_commands import mcp_app

app = typer.Typer(
    help="heterarchy-alexandria command line client.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(mcp_app, name="mcp")
app.add_typer(memory_steward_app, name="memory-steward")
app.add_typer(vault_app, name="vault")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the heterarchy-alexandria command tree.

    Args:
        argv: Optional command arguments without the executable name.

    Returns:
        Process-style exit code.
    """
    try:
        result = get_command(app).main(
            args=list(argv) if argv is not None else None,
            prog_name="heterarchy-alexandria",
            standalone_mode=False,
        )
        if isinstance(result, int):
            return result
    except typer.Exit as exc:
        return int(exc.exit_code or 0)
    except click.ClickException as exc:
        exc.show(file=sys.stderr)
        return exc.exit_code
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
