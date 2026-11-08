"""MCP public-contract regression harness.

Proves, for every registered MCP tool, that the advertised JSON contract and
the runtime agree in both directions:

1. consumption — every tool accepts a minimal legal JSON request synthesized
   from its own advertised input schema through the framework's production
   argument-validation path;
2. emission — every typed tool serializes its declared response schema into
   JSON that validates against the advertised output schema and contains no
   leaked Python/domain objects;
3. golden fixtures — the 2026-09-30 dogfood failures stay fixed end to end.

A schema that advertises a value the runtime cannot consume or emit fails CI
before merge.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, get_args, get_origin, get_type_hints

import httpx
import jsonschema
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.server_runtime import build_mcp_server
from app.platform.config.mcp_config import McpApiConfig
from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONValue

_ISO_DATETIME = "2026-01-01T00:00:00+00:00"
_SHA256_PATTERN_MARKERS = ("{64}",)
_DATE_PATTERN_MARKERS = (r"\d{4}", r"\d{2}", r"\d{2}")


def _stub_client(
    response_payload: JSONValue,
) -> tuple[AlexandriaApiClient, list[JSONValue]]:
    """Build one backend client that records request payloads.

    Args:
        response_payload: JSON payload returned for every backend call.

    Returns:
        Client and the list of recorded request payloads.
    """

    recorded: list[JSONValue] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        recorded.append(json.loads(body) if body else None)
        return httpx.Response(200, content=dumps_json(response_payload))

    client = AlexandriaApiClient(
        McpApiConfig(base_url="http://backend:8000", timeout=12.0),
        transport=httpx.MockTransport(transport),
    )
    return client, recorded


def _synthetic_string(schema: dict[str, Any]) -> str:
    """Synthesize one minimal string satisfying the schema constraints.

    Args:
        schema: Advertised JSON-schema string constraints.

    Returns:
        Minimal legal string value.

    Raises:
        AssertionError: When the constraint vocabulary is unknown, so new
            constraint kinds force explicit harness support instead of a
            silent gap.
    """
    pattern = schema.get("pattern")
    if pattern is not None:
        if all(marker in pattern for marker in _SHA256_PATTERN_MARKERS):
            return "a" * 64
        if all(marker in pattern for marker in _DATE_PATTERN_MARKERS):
            return "2026-01-01"
        raise AssertionError(f"unsupported advertised string pattern: {pattern!r}")
    min_length = schema.get("minLength", 1)
    return "a" * max(int(min_length), 1)


def _generate_value(schema: dict[str, Any], root: dict[str, Any]) -> JSONValue:
    """Synthesize one minimal legal value for one advertised JSON schema node.

    Args:
        schema: JSON-schema node to satisfy.
        root: Root schema used to resolve local references.

    Returns:
        Minimal legal JSON value.

    Raises:
        AssertionError: When the node cannot be synthesized, so a new advertised
            constraint kind forces explicit harness support.
    """
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), f"unsupported remote reference: {ref}"
        target: Any = root
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return _generate_value(target, root)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            for branch in schema[combinator]:
                try:
                    return _generate_value(branch, root)
                except AssertionError:
                    continue
            raise AssertionError(f"no branch of {combinator} could be synthesized")
    if "allOf" in schema:
        merged = {key: value for key, value in schema.items() if key != "allOf"}
        for partial in schema["allOf"]:
            if isinstance(partial, dict) and "$ref" not in partial:
                merged.update(partial)
        return _generate_value(merged, root)
    declared_type = schema.get("type")
    if isinstance(declared_type, list):
        declared_type = declared_type[0]
    if declared_type == "object":
        properties = schema.get("properties", {})
        required = [name for name in schema.get("required", []) if name in properties]
        required.extend(
            name
            for name, sub in properties.items()
            # Literal union tags carry a default, so they are absent from
            # `required` while the discriminated union still needs the tag.
            if "const" in sub and name not in required
        )
        if not required:
            # Cross-field validators (for example exactly-one selectors) are
            # invisible to JSON schema; selecting one optional member is the
            # minimal instance that satisfies the common require-one shape.
            required = list(properties)[:1]
        return {name: _generate_value(properties[name], root) for name in required}
    if declared_type == "array":
        min_items = int(schema.get("minItems", 0))
        if min_items == 0:
            return []
        return [_generate_value(schema["items"], root)] * min_items
    if declared_type == "string":
        if schema.get("format") == "date-time":
            return _ISO_DATETIME
        return _synthetic_string(schema)
    if declared_type == "integer":
        minimum = schema.get("minimum", 1)
        maximum = schema.get("maximum")
        if maximum is not None and minimum > maximum:
            minimum = maximum
        return int(minimum)
    if declared_type == "number":
        return float(schema.get("minimum", 0.5))
    if declared_type == "boolean":
        return False
    if declared_type == "null":
        return None
    raise AssertionError(f"cannot synthesize advertised schema node: {schema!r}")


def _minimal_request(tool_parameters: dict[str, Any]) -> dict[str, Any]:
    """Synthesize one minimal legal request for one advertised tool schema.

    Args:
        tool_parameters: Advertised tool input schema.

    Returns:
        Minimal legal JSON request arguments.
    """
    generated = _generate_value(tool_parameters, tool_parameters)
    assert isinstance(generated, dict)
    # The mutation-outcome selector has a runtime exactly-one validator that
    # JSON Schema cannot express. Choose the original-key branch explicitly
    # so the harness supplies a legal request without weakening that validator.
    request = generated.get("request")
    if (
        isinstance(request, dict)
        and request.get("operation") in {"verified_upsert", "relate", "note_write"}
        and "idempotency_key" not in request
        and "mutation_id" not in request
    ):
        request["idempotency_key"] = "a"
    return generated


def _assert_json_primitives(value: JSONValue, path: str = "$") -> None:
    """Assert that one emitted value contains only JSON primitives.

    Args:
        value: Emitted structured-content value.
        path: Location used in failure messages.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str), f"non-string key at {path}"
            _assert_json_primitives(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_primitives(item, f"{path}[{index}]")
        return
    raise AssertionError(f"non-JSON value leaked at {path}: {type(value).__name__}")


def _run_tool(tool: Any, arguments: dict[str, Any]) -> Any:
    """Run one registered tool through the framework production path.

    Args:
        tool: Framework tool object.
        arguments: Raw decoded JSON arguments.

    Returns:
        CallToolResult produced by the framework conversion.
    """
    return asyncio.run(tool.run(dict(arguments), None, convert_result=True))


def _declares_typed_response(tool: Any) -> bool:
    """Return whether one tool declares a typed response schema.

    Args:
        tool: Framework tool object.

    Returns:
        True when the return annotation names Pydantic response models, as
        opposed to pass-through ``JSONValue`` payloads without a declared
        schema.
    """
    hint = get_type_hints(tool.fn).get("return")
    candidates = get_args(hint) if get_origin(hint) else (hint,)
    return any(
        isinstance(candidate, type) and issubclass(candidate, BaseModel)
        for candidate in candidates
    )


def test_every_mcp_tool_consumes_its_advertised_json_request() -> None:
    """Every registered tool must accept a minimal legal JSON request."""
    client, _ = _stub_client({"ok": True})
    server = build_mcp_server(client=client)
    failures: list[str] = []
    for tool in server._tool_manager.list_tools():
        try:
            tool.fn_metadata.validate_arguments(_minimal_request(tool.parameters))
        except Exception as exc:
            failures.append(f"{tool.name}: {exc}")
    assert not failures, (
        "advertised JSON requests rejected by the runtime:\n" + "\n".join(failures)
    )


def test_every_typed_mcp_tool_emits_schema_valid_json() -> None:
    """Every typed tool must emit JSON valid against its advertised schema."""
    probe_client, _ = _stub_client({"ok": True})
    probe_server = build_mcp_server(client=probe_client)
    typed_output_schemas = {
        tool.name: tool.output_schema
        for tool in probe_server._tool_manager.list_tools()
        if tool.output_schema is not None and _declares_typed_response(tool)
    }
    failures: list[str] = []
    for name, output_schema in typed_output_schemas.items():
        try:
            # Union returns are wrapped as {"result": ...} at the tool
            # boundary; the backend serves the unwrapped declared payload.
            # References still resolve against the wrapped root schema.
            wrapped = probe_server._tool_manager.get_tool(name).fn_metadata.wrap_output
            backend_schema = (
                output_schema["properties"]["result"] if wrapped else output_schema
            )
            response_payload = _generate_value(backend_schema, output_schema)
            client, _ = _stub_client(response_payload)
            server = build_mcp_server(client=client)
            tool = server._tool_manager.get_tool(name)
            assert tool is not None
            result = _run_tool(tool, _minimal_request(tool.parameters))
            assert not result.is_error, f"{name}: tool reported an error"
            structured = result.structured_content
            assert structured is not None, f"{name}: missing structured content"
            _assert_json_primitives(structured)
            jsonschema.validate(structured, tool.output_schema)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    assert not failures, (
        "declared responses not emitted as schema-valid JSON:\n" + "\n".join(failures)
    )


def test_memory_cycle_golden_fixture_end_to_end() -> None:
    """The 2026-09-30 memory-cycle JSON fixture must complete end to end."""
    response_payload: JSONValue = {
        "operation": "dry_run",
        "status": "PREVIEW",
        "idempotency_key": "contract-test",
        "plan_hash": "a" * 64,
        "project": "heterarchy-alexandria",
        "workspace_id": None,
        "scope": "PROJECT",
        "window_start": "2026-09-28T00:00:00+09:00",
        "window_end": "2026-09-29T23:59:59+09:00",
        "replayed": False,
        "scanned": 0,
        "total_available": 0,
        "candidate_count": 0,
        "source_snapshot": [],
        "current_compact": None,
        "buckets": {
            bucket: []
            for bucket in (
                "retained_facts",
                "duplicates",
                "supersession_candidates",
                "contradictions",
                "compact_changes",
                "summary_candidates",
                "relationship_changes",
                "archive_candidates",
                "review_required",
            )
        },
        "child_outcomes": [],
        "compact_change": None,
        "phases": [],
        "warnings": [],
        "elapsed_ms": 1.0,
        "query_count": None,
        "hard_delete_performed": False,
    }
    client, recorded = _stub_client(response_payload)
    server = build_mcp_server(client=client)
    tool = server._tool_manager.get_tool("alexandria_memory_cycle")
    assert tool is not None
    arguments = {
        "request": {
            "project": "heterarchy-alexandria",
            "scope": "PROJECT",
            "window_start": "2026-09-28T00:00:00+09:00",
            "window_end": "2026-09-29T23:59:59+09:00",
            "idempotency_key": "contract-test",
            "operation": "dry_run",
        }
    }
    result = _run_tool(tool, arguments)
    assert not result.is_error
    assert result.structured_content is not None
    _assert_json_primitives(result.structured_content)
    jsonschema.validate(result.structured_content, tool.output_schema)
    assert recorded == [
        {
            "project": "heterarchy-alexandria",
            "scope": "PROJECT",
            "window_start": "2026-09-28T00:00:00+09:00",
            "window_end": "2026-09-29T23:59:59+09:00",
            "idempotency_key": "contract-test",
            "operation": "dry_run",
            "max_contexts": 100,
        }
    ]


def test_memory_cycle_boundary_rejects_invalid_json_primitives() -> None:
    """Naive timestamps and unknown scopes stay rejected at the boundary."""
    client, _ = _stub_client({"ok": True})
    server = build_mcp_server(client=client)
    tool = server._tool_manager.get_tool("alexandria_memory_cycle")
    assert tool is not None
    base = {
        "request": {
            "project": "heterarchy-alexandria",
            "scope": "PROJECT",
            "window_start": "2026-09-28T00:00:00+09:00",
            "window_end": "2026-09-29T23:59:59+09:00",
            "idempotency_key": "contract-test",
            "operation": "dry_run",
        }
    }
    naive = json.loads(json.dumps(base))
    naive["request"]["window_start"] = "2026-09-28T00:00:00"
    with pytest.raises(Exception, match="timezone-aware"):
        _run_tool(tool, naive)
    invalid_scope = json.loads(json.dumps(base))
    invalid_scope["request"]["scope"] = "GALAXY"
    with pytest.raises(ToolError):
        _run_tool(tool, invalid_scope)


def test_recall_golden_fixture_with_unavailable_provenance() -> None:
    """AUTO recall must pass with omitted unavailable provenance evidence."""
    probe_client, _ = _stub_client({"ok": True})
    probe_server = build_mcp_server(client=probe_client)
    probe_tool = probe_server._tool_manager.get_tool("alexandria_recall")
    assert probe_tool is not None
    backend_response = _generate_value(
        probe_tool.output_schema, probe_tool.output_schema
    )
    matches_schema = probe_tool.output_schema["properties"]["matches"]
    backend_response["matches"] = [
        _generate_value(matches_schema["items"], probe_tool.output_schema)
    ]
    client, recorded = _stub_client(backend_response)
    server = build_mcp_server(client=client)
    tool = server._tool_manager.get_tool("alexandria_recall")
    assert tool is not None
    result = _run_tool(
        tool,
        {
            "request": {
                "query": "contract harness probe",
                "project": "heterarchy-alexandria",
            }
        },
    )
    assert not result.is_error
    structured = result.structured_content
    assert structured is not None
    _assert_json_primitives(structured)
    jsonschema.validate(structured, tool.output_schema)
    assert "scope_mode" in structured
    assert len(structured["matches"]) == 1
    _assert_json_primitives(recorded[0])


def test_verified_upsert_golden_fixture_and_same_key_replay() -> None:
    """String alexandria_type writes must work and replay identically."""
    probe_client, _ = _stub_client({"ok": True})
    probe_server = build_mcp_server(client=probe_client)
    probe_tool = probe_server._tool_manager.get_tool("alexandria_verified_upsert")
    assert probe_tool is not None
    backend_response = _generate_value(
        probe_tool.output_schema, probe_tool.output_schema
    )
    client, recorded = _stub_client(backend_response)
    server = build_mcp_server(client=client)
    tool = server._tool_manager.get_tool("alexandria_verified_upsert")
    assert tool is not None
    arguments = {
        "request": {
            "identity": {
                "project": "heterarchy-alexandria",
                "report": "ops",
                "date": "2026-09-30",
                "entity": "harness",
            },
            "title": "Harness",
            "body": "# Harness",
            "alexandria_type": "context",
            "idempotency_key": "contract-test:upsert:2026-09-30",
        }
    }
    first = _run_tool(tool, arguments)
    assert not first.is_error
    assert first.structured_content is not None
    _assert_json_primitives(first.structured_content)
    jsonschema.validate(first.structured_content, tool.output_schema)
    replay = _run_tool(tool, arguments)
    assert not replay.is_error
    assert recorded[0] == recorded[1], "same-key replay must send an identical payload"


def test_invalid_alexandria_type_rejected_at_boundary() -> None:
    """Unknown alexandria_type strings stay rejected before the gateway."""
    client, _ = _stub_client({"ok": True})
    server = build_mcp_server(client=client)
    tool = server._tool_manager.get_tool("alexandria_verified_upsert")
    assert tool is not None
    arguments = {
        "request": {
            "identity": {
                "project": "heterarchy-alexandria",
                "report": "ops",
                "date": "2026-09-30",
                "entity": "harness",
            },
            "title": "Harness",
            "body": "# Harness",
            "alexandria_type": "not-a-note-type",
            "idempotency_key": "contract-test:upsert:invalid",
        }
    }
    with pytest.raises(ToolError):
        _run_tool(tool, arguments)
