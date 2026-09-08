---
name: alexandria-library
description: Use when current/local Hermes context, memory, skills, prompts, graph-related notes, or Memory Steward state may help the task, especially when agents must search or safely update scoped Obsidian-backed memory without overwriting another agent.
---

# Alexandria Library

Use Alexandria as an optional local-first knowledge library for Hermes.

## When to use
- Search local/current context before asking the user to repeat prior decisions.
- When local/current context is insufficient, read the current Memory Compact
  before deeper Context Vault recall/RAG.
- Recall project decisions, compact handoffs, skill candidates, prompts, and usage notes.
- Expand from a relevant seed note through the PostgreSQL/Rust related-note graph when direct search is not enough.
- Create or update reusable skills through the current MCP note-write boundary.

## Availability and opt-out contract
- Honor an explicit user instruction to avoid Alexandria for the current task/session.
- Do not claim a `policy`, `doctor`, or `vault` CLI command exists; the current CLI surface exposes `mcp` and `memory-steward` command groups.
- Prefer `alexandria_operational_readiness`, `alexandria_rag_status`, and other current `alexandria_*` MCP tools for runtime status.
- If MCP is unavailable, use the live HTTP readiness/RAG endpoints or the supported CLI command groups instead of inventing a legacy policy command.

## Status/diagnostics
- Primary readiness: `alexandria_operational_readiness()` or `GET /operations/readiness`.
- RAG health: `alexandria_rag_status()` or `GET /memory/contexts/rag/status`.
- Graph status: `alexandria_get_graph_projection_status()` when graph expansion matters; PostgreSQL is the graph source and Rust owns deterministic graph compute.
- CLI fallback is limited to commands actually shown by `heterarchy-alexandria --help`.

## Procedure
- Treat Alexandria as a helper, not an obligation.
- Long-term memory lookup order: current conversation and Hermes local memory
  first, then current Memory Compact, then Context Vault recall/RAG, then
  library skill/prompt search, then Hermes self-acquisition.
- Keep writes compact and durable: decisions, root causes, reusable plans, and skill candidates.
- Do not store secrets, transient task logs, or private credentials.

## Graph-aware discovery

Use search to find a relevant seed note before traversing the graph:

1. Run scoped FTS/vector/HYBRID search.
2. Read the best seed note and retain its stable `id` or canonical path.
3. Check `/obsidian/graph/projection/status` when graph expansion is useful.
4. Use `alexandria_get_related_notes(note_id=... | path=...)` to inspect related notes.
5. Read and cite the returned notes before using them as evidence.

The graph source is PostgreSQL indexed edge state, while Rust owns deterministic
projection, traversal, and candidate-selection compute. The application keeps a
rebuildable projection cache and does not simulate graph traversal in a second
runtime authority.
Missing or ambiguous targets are reported as counted, non-fatal rebuild issues
and are excluded from the active projection. Use detailed issue output only as a
bounded repair sample, not as the normal graph status payload.

## Safe Agent writes

Treat every update as a read-modify-write operation:

1. Read the current note and retain its `content_hash`.
2. Preserve its stable `id`, canonical path, and applicable scope identity.
3. Send the current hash as `expected_content_hash` when replacing the note.
4. If the backend returns `409 OBSIDIAN_WRITE_CONFLICT`, do not retry blindly.
5. Re-read the note, merge the newer content, and retry with the new hash.

An atomic file replacement prevents partial Markdown, but `expected_content_hash`
prevents one agent from silently overwriting another agent's completed update.

## Scope identity

- `AGENT` writes and recall require the intended `agent_id`.
- `SESSION` writes and recall require the intended `session_id`.
- `PROJECT` writes and recall require the intended `project`.
- For project-only Context recall, send both `project="<project>"` and
  `include_scopes=["PROJECT"]`. The REST field is `include_scopes`, not
  `recall_scopes`; using the response-field name in a request fails strict
  validation with HTTP `422`.
- Supply `workspace_id` whenever the caller has one.
- Do not broaden a missing identity to `GLOBAL`; fail closed and repair the request.
- Keep each concurrent task on its own database/request session.

After canonical writes, verify the note can be read back and that scoped
FTS/vector/HYBRID recall does not return another agent, session, project, or
workspace. For a project-only verification, require response
`recall_scopes=["PROJECT"]`, `effective_strategy="HYBRID"`, no warnings, a
relevant match, and vector/semantic scoring evidence.

When a write changes note links or graph-relevant metadata, finish with:

1. vault reindex;
2. queued embedding reindex when RAG reports missing or stale rows;
3. verify the graph projection returned by vault reindex; explicitly rebuild only when projection is stale, failed, skipped, or a diagnostic rebuild is required;
4. exact search/readback plus one related-note lookup from a known seed.

These maintenance steps are sequential. Retry HTTP `409` after the current
maintenance operation completes. Normal search reads the current index and does
not perform an implicit vault reindex.

## Evidence
- https://github.com/heterarchy-systems/heterarchy-alexandria/blob/main/README.md
- https://github.com/heterarchy-systems/heterarchy-alexandria/blob/main/backend/app/mcp_server/backend_tool_gateway.py

## Related Alexandria skills

- [[Skills/Active/Alexandria Operational Sync]] — vault, embedding, and graph projection recovery.
- `skills_alexandria/safe-markdown-storage/SKILL.md` — canonical Markdown write, integrity, path, and concurrency rules.
