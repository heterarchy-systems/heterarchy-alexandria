"""Typer app for Memory Steward maintenance operations."""

from __future__ import annotations

import typer

from app.cli.memory_steward_commands import register_memory_steward_commands

memory_steward_app = typer.Typer(
    help="Operate Memory Steward readiness and compaction workflows.",
    no_args_is_help=True,
    add_completion=False,
)
register_memory_steward_commands(memory_steward_app)
