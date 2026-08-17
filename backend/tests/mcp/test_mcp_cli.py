"""MCP CLI launch tests."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from enum import StrEnum

from app import cli
from app.cli import (
    maintenance_gateway as cli_maintenance_gateway,
    mcp_server_commands as cli_mcp,
    memory_steward_commands as cli_memory_steward,
)
from app.cli.type_validate.command_options import RequiredMcpTool
from app.cli.type_validate.mcp_protocol_payload_contracts import (
    decode_mcp_json_response,
    mcp_tool_names,
)
from app.mcp_server import server_runtime
from app.mcp_server.type_validate.transport_contracts import McpTransport
from app.shared.serialization.orjson_codec import loads_json


class FakeMcpServer:
    """Tiny FastMCP stand-in for CLI launch verification."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, str | None]] = []

    def run(self, transport: str = "stdio", mount_path: str | None = None) -> None:
        """Record the requested transport instead of blocking on a server loop."""
        self.runs.append((transport, mount_path))


def test_cli_maintenance_gateway_defers_backend_tool_gateway_import() -> None:
    """CLI import should not load the broad backend gateway just to render help."""
    sys.modules.pop("app.mcp_server.backend_tool_gateway", None)

    importlib.reload(cli_maintenance_gateway)

    assert "app.mcp_server.backend_tool_gateway" not in sys.modules


def test_cli_type_contracts_use_str_enums() -> None:
    """CLI transport and required MCP tool contracts should be StrEnum values."""
    assert issubclass(McpTransport, StrEnum)
    assert issubclass(RequiredMcpTool, StrEnum)
    assert [transport.value for transport in McpTransport] == [
        "stdio",
        "sse",
        "streamable-http",
    ]
    assert [tool.value for tool in RequiredMcpTool] == [
        "alexandria_memory_steward_readiness",
        "alexandria_memory_steward_refresh_current_compact",
        "alexandria_vault_review_queue",
        "alexandria_vault_review_move_plan",
        "alexandria_vault_review_apply_moves",
    ]


def test_mcp_runtime_main_runs_selected_transport(monkeypatch) -> None:
    """Runtime MCP entrypoint should run FastMCP with the requested transport."""
    fake_server = FakeMcpServer()
    monkeypatch.setattr(
        server_runtime,
        "build_mcp_server",
        lambda transport_host=server_runtime.DEFAULT_MCP_TRANSPORT_HOST: fake_server,
    )

    exit_code = server_runtime.main(["--transport", "streamable-http"])

    assert exit_code == 0
    assert fake_server.runs == [("streamable-http", None)]


def test_cli_mcp_serve_defaults_to_stdio(monkeypatch) -> None:
    """Package CLI should keep the Hermes MCP launch contract available."""
    received: list[Sequence[str]] = []

    def fake_main(argv: Sequence[str] | None = None) -> int:
        received.append(tuple(argv or ()))
        return 0

    monkeypatch.setattr(server_runtime, "main", fake_main)

    exit_code = cli.main(["mcp", "serve"])

    assert exit_code == 0
    assert received == [("--transport", "stdio")]


def test_cli_mcp_smoke_tools_returns_zero_when_required_tools_exist(
    monkeypatch,
    capsys,
) -> None:
    """MCP smoke CLI should succeed when required live tools are exposed."""
    received: list[tuple[str | None, tuple[str, ...]]] = []

    async def fake_smoke(*, settings, mcp_url, required_tools: Sequence[str]):
        received.append((mcp_url, tuple(required_tools)))
        return {"ok": True, "missing_tools": [], "tool_count": 5}

    monkeypatch.setattr(cli_mcp, "_mcp_smoke_tools", fake_smoke)

    exit_code = cli.main(["mcp", "smoke-tools"])

    assert exit_code == 0
    assert received == [
        (
            None,
            (
                "alexandria_memory_steward_readiness",
                "alexandria_memory_steward_refresh_current_compact",
                "alexandria_vault_review_queue",
                "alexandria_vault_review_move_plan",
                "alexandria_vault_review_apply_moves",
            ),
        )
    ]
    assert loads_json(capsys.readouterr().out) == {
        "ok": True,
        "missing_tools": [],
        "tool_count": 5,
    }


def test_cli_mcp_smoke_tools_returns_attention_exit_when_tools_are_missing(
    monkeypatch,
    capsys,
) -> None:
    """MCP smoke CLI should fail non-zero when requested tools are missing."""
    received: list[tuple[str | None, tuple[str, ...]]] = []

    async def fake_smoke(*, settings, mcp_url, required_tools: Sequence[str]):
        received.append((mcp_url, tuple(required_tools)))
        return {
            "ok": False,
            "missing_tools": ["alexandria_memory_steward_readiness"],
            "tool_count": 1,
        }

    monkeypatch.setattr(cli_mcp, "_mcp_smoke_tools", fake_smoke)

    exit_code = cli.main(
        [
            "mcp",
            "smoke-tools",
            "--mcp-url",
            "http://backend:8000/mcp/",
            "--required-tool",
            "alexandria_memory_steward_readiness",
        ]
    )

    assert exit_code == 2
    assert received == [
        ("http://backend:8000/mcp/", ("alexandria_memory_steward_readiness",))
    ]
    assert loads_json(capsys.readouterr().out) == {
        "ok": False,
        "missing_tools": ["alexandria_memory_steward_readiness"],
        "tool_count": 1,
    }


def test_cli_mcp_tools_response_parser_accepts_json_and_sse_payloads() -> None:
    """MCP smoke parser should handle JSON and SSE tools/list responses."""
    json_payload = (
        '{"jsonrpc":"2.0","id":2,"result":{"tools":'
        '[{"name":"alexandria_memory_steward_readiness"}]}}'
    )
    sse_payload = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":2,"result":{"tools":'
        '[{"name":"alexandria_memory_steward_refresh_current_compact"}]}}\n\n'
    )

    json_tools = mcp_tool_names(decode_mcp_json_response(json_payload))
    sse_tools = mcp_tool_names(decode_mcp_json_response(sse_payload))

    assert json_tools == {"alexandria_memory_steward_readiness"}
    assert sse_tools == {"alexandria_memory_steward_refresh_current_compact"}


def test_cli_memory_steward_prints_gateway_payload(monkeypatch, capsys) -> None:
    """Librarian readiness CLI should expose the MCP readiness workflow locally."""
    received: list[tuple[str | None, int]] = []

    async def fake_readiness(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
    ):
        received.append((project, max_compact_age_days))
        return {"ready": True, "warnings": []}

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_readiness",
        fake_readiness,
    )

    exit_code = cli.main(
        [
            "memory-steward",
            "readiness",
            "--project",
            "heterarchy-alexandria",
            "--max-compact-age-days",
            "14",
        ]
    )

    assert exit_code == 0
    assert received == [("heterarchy-alexandria", 14)]
    assert loads_json(capsys.readouterr().out) == {"ready": True, "warnings": []}


def test_cli_vault_review_queue_summary_maps_scope_options(
    monkeypatch,
    capsys,
) -> None:
    """Review queue CLI should expose compact curation counts and top candidate."""
    received: list[tuple[str | None, str | None, int]] = []

    async def fake_review_queue(
        client,
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
    ):
        received.append((project, scope_path, limit))
        return {
            "total": 2,
            "items": [
                {
                    "id": "ctx-inbox",
                    "path": "Alexandria/_Inbox/Captures/Captured.md",
                    "reason": "inbox_capture",
                    "recommended_action": "classify_and_promote",
                    "suggested_destination_path": (
                        "Alexandria/Contexts/Projects/Captured.md"
                    ),
                    "confidence": 0.85,
                    "requires_human_review": False,
                },
                {
                    "id": "skill-draft",
                    "path": "Alexandria/Skills/Drafts/Draft.md",
                    "reason": "skill_draft",
                    "recommended_action": "promote_to_active_or_mark_deprecated",
                    "suggested_destination_path": "Alexandria/Skills/Active/Draft.md",
                    "confidence": 0.70,
                    "requires_human_review": True,
                },
            ],
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_vault_review_queue",
        fake_review_queue,
    )

    exit_code = cli.main(
        [
            "vault",
            "review-queue",
            "--project",
            "heterarchy-alexandria",
            "--scope-path",
            "Alexandria/_Inbox",
            "--limit",
            "5",
            "--summary",
        ]
    )

    assert exit_code == 0
    assert received == [("heterarchy-alexandria", "Alexandria/_Inbox", 5)]
    assert loads_json(capsys.readouterr().out) == {
        "total": 2,
        "auto_move_candidates": 1,
        "manual_review_required": 1,
        "top_item_id": "ctx-inbox",
        "top_item_path": "Alexandria/_Inbox/Captures/Captured.md",
        "top_item_reason": "inbox_capture",
        "top_item_action": "classify_and_promote",
        "top_item_confidence": 0.85,
        "top_item_requires_human_review": False,
    }


def test_cli_vault_review_move_plan_maps_scope_options(
    monkeypatch,
    capsys,
) -> None:
    """Review move-plan CLI should call the non-mutating safe plan gateway."""
    received: list[tuple[str | None, str | None, int]] = []

    async def fake_move_plan(
        client,
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
    ):
        received.append((project, scope_path, limit))
        return {
            "status": "ready",
            "moves": [
                {
                    "source_path": "Alexandria/_Inbox/Captures/Captured.md",
                    "destination_path": "Alexandria/Contexts/Projects/Captured.md",
                }
            ],
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_vault_review_move_plan",
        fake_move_plan,
    )

    exit_code = cli.main(
        [
            "vault",
            "review-move-plan",
            "--project",
            "heterarchy-alexandria",
            "--scope-path",
            "Alexandria/_Inbox",
            "--limit",
            "5",
        ]
    )

    assert exit_code == 0
    assert received == [("heterarchy-alexandria", "Alexandria/_Inbox", 5)]
    assert loads_json(capsys.readouterr().out) == {
        "status": "ready",
        "moves": [
            {
                "source_path": "Alexandria/_Inbox/Captures/Captured.md",
                "destination_path": "Alexandria/Contexts/Projects/Captured.md",
            }
        ],
    }


def test_cli_vault_review_apply_moves_maps_safety_options(
    monkeypatch,
    capsys,
) -> None:
    """Review apply CLI should pass explicit report/reindex/verification controls."""
    received: list[
        tuple[str | None, str | None, int, str | None, bool, str | None, bool]
    ] = []

    async def fake_apply_moves(
        client,
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
        report_path: str | None = None,
        reindex: bool = True,
        verification_query: str | None = None,
        confirm_apply: bool = False,
    ):
        received.append(
            (
                project,
                scope_path,
                limit,
                report_path,
                reindex,
                verification_query,
                confirm_apply,
            )
        )
        return {
            "status": "applied",
            "hard_delete_performed": False,
            "moved": [],
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_vault_review_apply_moves",
        fake_apply_moves,
    )

    exit_code = cli.main(
        [
            "vault",
            "review-apply-moves",
            "--project",
            "heterarchy-alexandria",
            "--scope-path",
            "Alexandria/_Inbox",
            "--limit",
            "5",
            "--report-path",
            "Alexandria/_Ops/Librarian/Reports/cli-apply",
            "--confirm-apply",
            "--no-reindex",
            "--verification-query",
            "Captured",
        ]
    )

    assert exit_code == 0
    assert received == [
        (
            "heterarchy-alexandria",
            "Alexandria/_Inbox",
            5,
            "Alexandria/_Ops/Librarian/Reports/cli-apply",
            False,
            "Captured",
            True,
        )
    ]
    assert loads_json(capsys.readouterr().out) == {
        "status": "applied",
        "hard_delete_performed": False,
        "moved": [],
    }


def test_cli_vault_review_apply_moves_requires_confirm_when_plan_has_moves(
    monkeypatch,
    capsys,
) -> None:
    """Review apply CLI should not mutate when a non-empty plan lacks confirmation."""

    async def fake_apply_moves(*args, **kwargs):
        return {
            "status": "confirmation_required",
            "hard_delete_performed": False,
            "moved": [],
            "skipped": [],
            "ambiguous": [],
            "apply_skipped_reason": "confirm_apply_required",
            "move_plan": {
                "status": "ready",
                "hard_delete_performed": False,
                "moves": [
                    {
                        "source_path": "Alexandria/_Inbox/Captures/Captured.md",
                        "destination_path": (
                            "Alexandria/Contexts/Projects/Captured.md"
                        ),
                    }
                ],
                "skipped": [],
                "ambiguous": [],
            },
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_vault_review_apply_moves",
        fake_apply_moves,
    )

    exit_code = cli.main(["vault", "review-apply-moves"])

    assert exit_code == 2
    assert loads_json(capsys.readouterr().out) == {
        "status": "confirmation_required",
        "hard_delete_performed": False,
        "moved": [],
        "skipped": [],
        "ambiguous": [],
        "apply_skipped_reason": "confirm_apply_required",
        "move_plan": {
            "status": "ready",
            "hard_delete_performed": False,
            "moves": [
                {
                    "source_path": "Alexandria/_Inbox/Captures/Captured.md",
                    "destination_path": "Alexandria/Contexts/Projects/Captured.md",
                }
            ],
            "skipped": [],
            "ambiguous": [],
        },
    }


def test_cli_vault_review_apply_moves_skips_apply_when_plan_is_empty(
    monkeypatch,
    capsys,
) -> None:
    """Review apply CLI should print gateway no-op payloads as success."""
    gateway_called = False

    async def fake_apply_moves(*args, **kwargs):
        nonlocal gateway_called
        gateway_called = True
        return {
            "status": "no_op",
            "hard_delete_performed": False,
            "moved": [],
            "skipped": [],
            "ambiguous": [],
            "apply_skipped_reason": "review_move_plan_empty",
            "move_plan": {
                "status": "empty",
                "hard_delete_performed": False,
                "moves": [],
                "skipped": [],
                "ambiguous": [],
            },
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_vault_review_apply_moves",
        fake_apply_moves,
    )

    exit_code = cli.main(["vault", "review-apply-moves"])

    assert exit_code == 0
    assert gateway_called is True
    assert loads_json(capsys.readouterr().out) == {
        "status": "no_op",
        "hard_delete_performed": False,
        "moved": [],
        "skipped": [],
        "ambiguous": [],
        "apply_skipped_reason": "review_move_plan_empty",
        "move_plan": {
            "status": "empty",
            "hard_delete_performed": False,
            "moves": [],
            "skipped": [],
            "ambiguous": [],
        },
    }


def test_cli_memory_steward_refresh_current_compact_maps_apply_options(
    monkeypatch,
    capsys,
) -> None:
    """Compact refresh CLI should support dry-run/apply operating options."""
    received: list[tuple[str | None, int, bool, bool, str | None]] = []

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        received.append((project, max_compact_age_days, apply, force, covered_to))
        return {"status": "refreshed", "created": {"id": "compact-new"}}

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(
        [
            "memory-steward",
            "refresh-current-compact",
            "--project",
            "heterarchy-alexandria",
            "--max-compact-age-days",
            "7",
            "--apply",
            "--force",
            "--covered-to",
            "2026-07-15T00:00:00Z",
        ]
    )

    assert exit_code == 0
    assert received == [
        ("heterarchy-alexandria", 7, True, True, "2026-07-15T00:00:00Z")
    ]
    assert loads_json(capsys.readouterr().out) == {
        "status": "refreshed",
        "created": {"id": "compact-new"},
    }


def test_cli_memory_steward_preflight_returns_zero_when_ready(
    monkeypatch, capsys
) -> None:
    """Preflight should succeed when post-refresh readiness is ready."""
    received: list[tuple[str | None, int, bool, bool, str | None]] = []

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        received.append((project, max_compact_age_days, apply, force, covered_to))
        return {
            "status": "up_to_date",
            "post_refresh_readiness": {"ready": True, "warnings": []},
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(
        [
            "memory-steward",
            "preflight",
            "--project",
            "heterarchy-alexandria",
            "--max-compact-age-days",
            "30",
        ]
    )

    assert exit_code == 0
    assert received == [("heterarchy-alexandria", 30, False, False, None)]
    assert loads_json(capsys.readouterr().out)["status"] == "up_to_date"


def test_cli_memory_steward_preflight_returns_attention_exit_when_not_ready(
    monkeypatch,
    capsys,
) -> None:
    """Preflight should fail non-zero when readiness still needs attention."""

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        return {
            "status": "refresh_required",
            "post_refresh_readiness": {
                "ready": False,
                "warnings": ["current_memory_compact_stale"],
            },
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(
        ["memory-steward", "preflight", "--project", "heterarchy-alexandria"]
    )

    assert exit_code == 2
    payload = loads_json(capsys.readouterr().out)
    assert payload["post_refresh_readiness"]["warnings"] == [
        "current_memory_compact_stale"
    ]


def test_cli_memory_steward_preflight_can_apply_compact_refresh(
    monkeypatch,
    capsys,
) -> None:
    """Preflight should pass refresh controls through for startup automation."""
    received: list[tuple[str | None, int, bool, bool, str | None]] = []

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        received.append((project, max_compact_age_days, apply, force, covered_to))
        return {
            "status": "refreshed",
            "post_refresh_readiness": {"ready": True, "warnings": []},
        }

    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(
        [
            "memory-steward",
            "preflight",
            "--project",
            "heterarchy-alexandria",
            "--refresh-compact",
            "--force-refresh",
            "--covered-to",
            "2026-07-15T00:00:00Z",
        ]
    )

    assert exit_code == 0
    assert received == [
        ("heterarchy-alexandria", 30, True, True, "2026-07-15T00:00:00Z")
    ]
    assert loads_json(capsys.readouterr().out)["status"] == "refreshed"


def test_cli_memory_steward_check_combines_mcp_smoke_and_preflight(
    monkeypatch,
    capsys,
) -> None:
    """Memory Steward check should return one JSON result for startup automation."""
    smoke_calls: list[tuple[str | None, tuple[str, ...]]] = []
    preflight_calls: list[tuple[str | None, int, bool, bool, str | None]] = []

    async def fake_smoke(*, settings, mcp_url, required_tools: Sequence[str]):
        smoke_calls.append((mcp_url, tuple(required_tools)))
        return {"ok": True, "missing_tools": []}

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        preflight_calls.append(
            (project, max_compact_age_days, apply, force, covered_to)
        )
        return {
            "status": "up_to_date",
            "post_refresh_readiness": {"ready": True, "warnings": []},
        }

    monkeypatch.setattr(cli_memory_steward, "_mcp_smoke_tools", fake_smoke)
    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(
        [
            "memory-steward",
            "check",
            "--project",
            "heterarchy-alexandria",
            "--max-compact-age-days",
            "14",
            "--refresh-compact",
            "--covered-to",
            "2026-07-15T00:00:00Z",
        ]
    )

    assert exit_code == 0
    assert smoke_calls == [
        (
            None,
            (
                "alexandria_memory_steward_readiness",
                "alexandria_memory_steward_refresh_current_compact",
                "alexandria_vault_review_queue",
                "alexandria_vault_review_move_plan",
                "alexandria_vault_review_apply_moves",
            ),
        )
    ]
    assert preflight_calls == [
        ("heterarchy-alexandria", 14, True, False, "2026-07-15T00:00:00Z")
    ]
    assert loads_json(capsys.readouterr().out) == {
        "ok": True,
        "mcp_smoke": {"ok": True, "missing_tools": []},
        "preflight": {
            "status": "up_to_date",
            "post_refresh_readiness": {"ready": True, "warnings": []},
        },
    }


def test_cli_memory_steward_check_fails_when_mcp_smoke_is_missing_tools(
    monkeypatch,
    capsys,
) -> None:
    """Memory Steward check should fail when MCP does not expose required tools."""

    async def fake_smoke(*, settings, mcp_url, required_tools: Sequence[str]):
        return {"ok": False, "missing_tools": ["alexandria_memory_steward_readiness"]}

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        return {
            "status": "up_to_date",
            "post_refresh_readiness": {"ready": True, "warnings": []},
        }

    monkeypatch.setattr(cli_memory_steward, "_mcp_smoke_tools", fake_smoke)
    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(
        ["memory-steward", "check", "--project", "heterarchy-alexandria"]
    )

    assert exit_code == 2
    payload = loads_json(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["mcp_smoke"]["missing_tools"] == [
        "alexandria_memory_steward_readiness"
    ]


def test_cli_memory_steward_check_summary_prints_compact_status(
    monkeypatch,
    capsys,
) -> None:
    """Memory Steward check summary should emit only small status fields."""

    async def fake_smoke(*, settings, mcp_url, required_tools: Sequence[str]):
        return {
            "ok": True,
            "mcp_url": "http://backend:8000/mcp/",
            "required_tools": [
                "alexandria_memory_steward_readiness",
                "alexandria_memory_steward_refresh_current_compact",
                "alexandria_vault_review_queue",
                "alexandria_vault_review_move_plan",
                "alexandria_vault_review_apply_moves",
            ],
            "missing_tools": [],
            "tool_count": 39,
        }

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        return {
            "status": "up_to_date",
            "refresh_required": False,
            "created": None,
            "compact_draft": {"markdown_body": "# long body"},
            "post_refresh_readiness": {
                "ready": True,
                "warnings": [],
                "rag": {
                    "fts": "HEALTHY",
                    "vector": "HEALTHY",
                    "embedding": "HEALTHY",
                },
                "review_queue": {
                    "total": 0,
                    "auto_move_candidates": 0,
                    "manual_review_required": 0,
                },
                "current_memory_compact": {
                    "id": "compact-current",
                    "age_days": 0,
                    "max_age_days": 30,
                },
                "next_actions": [],
            },
        }

    monkeypatch.setattr(cli_memory_steward, "_mcp_smoke_tools", fake_smoke)
    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(["memory-steward", "check", "--summary"])

    assert exit_code == 0
    assert loads_json(capsys.readouterr().out) == {
        "ok": True,
        "mcp_url": "http://backend:8000/mcp/",
        "mcp_tool_count": 39,
        "mcp_required_tools_count": 5,
        "mcp_required_tools": [
            "alexandria_memory_steward_readiness",
            "alexandria_memory_steward_refresh_current_compact",
            "alexandria_vault_review_queue",
            "alexandria_vault_review_move_plan",
            "alexandria_vault_review_apply_moves",
        ],
        "mcp_missing_tools": [],
        "preflight_status": "up_to_date",
        "refresh_required": False,
        "created": False,
        "created_compact_id": None,
        "ready": True,
        "warnings": [],
        "current_compact_id": "compact-current",
        "compact_age_days": 0,
        "max_compact_age_days": 30,
        "rag_fts": "HEALTHY",
        "rag_vector": "HEALTHY",
        "rag_embedding": "HEALTHY",
        "review_queue_total": 0,
        "review_auto_move_candidates": 0,
        "review_manual_required": 0,
        "next_actions_count": 0,
        "next_action": None,
        "next_action_tool": None,
    }


def test_cli_memory_steward_check_summary_fails_with_compact_status_fields(
    monkeypatch,
    capsys,
) -> None:
    """Failed summary should stay compact while surfacing attention signals."""

    async def fake_smoke(*, settings, mcp_url, required_tools: Sequence[str]):
        return {
            "ok": False,
            "mcp_url": "http://backend:8000/mcp/",
            "required_tools": [
                "alexandria_memory_steward_readiness",
                "alexandria_memory_steward_refresh_current_compact",
                "alexandria_vault_review_queue",
                "alexandria_vault_review_move_plan",
                "alexandria_vault_review_apply_moves",
            ],
            "missing_tools": ["alexandria_memory_steward_refresh_current_compact"],
            "tool_count": 38,
        }

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        return {
            "status": "refresh_required",
            "refresh_required": True,
            "created": None,
            "post_refresh_readiness": {
                "ready": False,
                "warnings": ["current_memory_compact_stale"],
                "rag": {
                    "fts": "HEALTHY",
                    "vector": "HEALTHY",
                    "embedding": "HEALTHY",
                },
                "review_queue": {
                    "total": 1,
                    "auto_move_candidates": 0,
                    "manual_review_required": 1,
                },
                "current_memory_compact": {
                    "id": "compact-stale",
                    "age_days": 45,
                    "max_age_days": 30,
                },
                "next_actions": [
                    {
                        "priority": 20,
                        "code": "refresh_current_memory_compact",
                        "tool": "alexandria_memory_steward_refresh_current_compact",
                        "summary": "Refresh the CURRENT Memory Compact.",
                        "dry_run_first": True,
                    }
                ],
            },
        }

    monkeypatch.setattr(cli_memory_steward, "_mcp_smoke_tools", fake_smoke)
    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(["memory-steward", "check", "--summary"])

    assert exit_code == 2
    assert loads_json(capsys.readouterr().out) == {
        "ok": False,
        "mcp_url": "http://backend:8000/mcp/",
        "mcp_tool_count": 38,
        "mcp_required_tools_count": 5,
        "mcp_required_tools": [
            "alexandria_memory_steward_readiness",
            "alexandria_memory_steward_refresh_current_compact",
            "alexandria_vault_review_queue",
            "alexandria_vault_review_move_plan",
            "alexandria_vault_review_apply_moves",
        ],
        "mcp_missing_tools": ["alexandria_memory_steward_refresh_current_compact"],
        "preflight_status": "refresh_required",
        "refresh_required": True,
        "created": False,
        "created_compact_id": None,
        "ready": False,
        "warnings": ["current_memory_compact_stale"],
        "current_compact_id": "compact-stale",
        "compact_age_days": 45,
        "max_compact_age_days": 30,
        "rag_fts": "HEALTHY",
        "rag_vector": "HEALTHY",
        "rag_embedding": "HEALTHY",
        "review_queue_total": 1,
        "review_auto_move_candidates": 0,
        "review_manual_required": 1,
        "next_actions_count": 1,
        "next_action": "refresh_current_memory_compact",
        "next_action_tool": "alexandria_memory_steward_refresh_current_compact",
    }


def test_cli_memory_steward_check_summary_reports_created_compact_without_body(
    monkeypatch,
    capsys,
) -> None:
    """Summary should report created compact id without embedding long content."""

    async def fake_smoke(*, settings, mcp_url, required_tools: Sequence[str]):
        return {
            "ok": True,
            "mcp_url": "http://backend:8000/mcp/",
            "required_tools": [
                "alexandria_memory_steward_readiness",
                "alexandria_memory_steward_refresh_current_compact",
                "alexandria_vault_review_queue",
                "alexandria_vault_review_move_plan",
                "alexandria_vault_review_apply_moves",
            ],
            "missing_tools": [],
            "tool_count": 39,
        }

    async def fake_refresh(
        client,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ):
        return {
            "status": "refreshed",
            "refresh_required": True,
            "created": {
                "id": "compact-new",
                "markdown_body": "# long body",
            },
            "post_refresh_readiness": {
                "ready": True,
                "warnings": [],
                "rag": {
                    "fts": "HEALTHY",
                    "vector": "HEALTHY",
                    "embedding": "HEALTHY",
                },
                "review_queue": {
                    "total": 0,
                    "auto_move_candidates": 0,
                    "manual_review_required": 0,
                },
                "current_memory_compact": {
                    "id": "compact-new",
                    "age_days": 0,
                    "max_age_days": 30,
                },
                "next_actions": [],
            },
        }

    monkeypatch.setattr(cli_memory_steward, "_mcp_smoke_tools", fake_smoke)
    monkeypatch.setattr(
        cli_maintenance_gateway.backend_tool_gateway,
        "alexandria_memory_steward_refresh_current_compact",
        fake_refresh,
    )

    exit_code = cli.main(["memory-steward", "check", "--summary", "--refresh"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "markdown_body" not in output
    assert "# long body" not in output
    assert loads_json(output) == {
        "ok": True,
        "mcp_url": "http://backend:8000/mcp/",
        "mcp_tool_count": 39,
        "mcp_required_tools_count": 5,
        "mcp_required_tools": [
            "alexandria_memory_steward_readiness",
            "alexandria_memory_steward_refresh_current_compact",
            "alexandria_vault_review_queue",
            "alexandria_vault_review_move_plan",
            "alexandria_vault_review_apply_moves",
        ],
        "mcp_missing_tools": [],
        "preflight_status": "refreshed",
        "refresh_required": True,
        "created": True,
        "created_compact_id": "compact-new",
        "ready": True,
        "warnings": [],
        "current_compact_id": "compact-new",
        "compact_age_days": 0,
        "max_compact_age_days": 30,
        "rag_fts": "HEALTHY",
        "rag_vector": "HEALTHY",
        "rag_embedding": "HEALTHY",
        "review_queue_total": 0,
        "review_auto_move_candidates": 0,
        "review_manual_required": 0,
        "next_actions_count": 0,
        "next_action": None,
        "next_action_tool": None,
    }
