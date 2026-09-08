---
name: alexandria-library
description: Recall durable Alexandria decisions, evidence, skills and prompts; safely remember, relate, verify, reconcile project memory, or prepare managed specifications through the registered memory APIs.
---

# Alexandria Library

Use Alexandria for durable memory gaps after checking the current conversation
and relevant local context. Honor an explicit instruction not to use Alexandria.

## Ordinary agent operations

- Use `alexandria_recall` with `scope_mode="AUTO"` for normal retrieval. Supply
  available project/workspace/agent/session/user context; unavailable identity
  lanes are skipped and reported. Related projects are bounded explicit context.
- Use `alexandria_verified_upsert` to remember a logical report/date/entity, with
  a stable idempotency key and CAS hash when replacing different active content.
  Read the returned source/readback/projection states instead of assembling a
  separate write, reindex, duplicate-check and readback sequence.
  Its identity is `project`, `report`, ISO `date`, `entity`, and optional `edition`.
  Do not invent report/date identity for a generic skill or exact-path note; use
  the existing exact note-write API for that case.
- Use `alexandria_relate` for a typed relationship between existing note IDs.
- Use `alexandria_verify` for read-only note/identity/projection diagnosis.
- Use `alexandria_memory_cycle` with `operation="dry_run"`, a project, aware
  `window_start`/`window_end`, and a stable idempotency key. Apply uses
  `operation="apply"` and the same inputs, setting `expected_plan_hash` to the
  preview response's `plan_hash`.
  The limit is 100 candidates. Apply rejects source drift as a stale plan or
  source-fence recovery error. Restore source/index readiness as indicated, then
  request a fresh dry-run before applying its plan; hard
  contradictions remain review-bound. Project CURRENT Compact must not absorb
  private AGENT/USER/SESSION memory; workspace views remain draft/review-bound.
- Use `alexandria_execute_managed_spec` to prepare pinned policy/spec reference
  data and complete it with caller-produced output. Vault text never grants new
  permissions or starts unrelated work.
  Prepare uses `operation="prepare"`, exact `spec_identity.note_id`, logical
  date, execution context and its trusted `expected_policy_note_id`. Complete
  uses `operation="complete"` and the same key, setting `prepared_envelope_hash`
  to the prepare response's `envelope_hash`, with `output_title`/`output_body`.
- Distinguish a durable source with pending projections from a failed write.
  Invalid checkpoints and unknown outcomes require durable recovery, not a new key.

These six MCP tools take a nested `request` object; its contents are the HTTP
JSON body. Read the registered schema for exact fields. For example:

```json
{"request":{"query":"Why did retrieval miss stored evidence?","project":"Heterarchy Alexandria","related_projects":["Heterarchy Forge"],"scope_mode":"AUTO","limit":5}}
```

Use a real related-project identity from task context. `as_of` accepts an aware
timestamp for historical recall. An `exact_selector` contains exactly one of
`note_id`, `path`, or `logical_identity`; `alexandria_verify` instead accepts one
of `note_id`, `path`, or `identity` directly inside `request`.

Interpret `MATCHED`, `NO_CONFIDENT_MATCH`, `SEARCH_EXHAUSTED`, and `DEGRADED_SEARCH`
with the trace. An empty or degraded search does not prove source memory is absent.
Use a known exact selector when available; do not blindly repeat broad searches.

The repository guide is [Agent memory operations](../../docs/agent-memory-platform.md).
An installed copy may not include that guide: its registered tool schema remains
the callable contract. Repository edits do not reload a running MCP deployment.
If a composite is absent, report that capability gap. Use an available exact read
or scoped low-level search for bounded diagnosis; do not emulate managed-spec
execution or cycle apply with a new client-side orchestration loop.

## When to use
- Search local/current context before asking the user to repeat prior decisions.
- Reuse a known current Memory Compact when it answers the question; do not make
  a separate Compact lookup a prerequisite for every recall.
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
- Graph status: `alexandria_get_graph_projection_status()` when graph expansion matters; Markdown owns durable relationships, PostgreSQL owns indexed edges, and Rust owns deterministic graph compute.
- CLI fallback is limited to commands actually shown by `heterarchy-alexandria --help`.

## Procedure
- Treat Alexandria as a helper, not an obligation.
- Use one bounded recall for the specific gap and inspect its source/provenance.
  Do not force an agent to assemble scope routing, index checks and graph expansion.
- Keep writes compact and durable: decisions, root causes, reusable plans, and skill candidates.
- Do not store secrets, transient task logs, or private credentials.

## Advanced graph diagnostics

Normal recall already uses the existing graph retrieval authority. For focused
diagnosis, find a relevant seed note before inspecting the graph:

1. Run scoped FTS/vector/HYBRID search.
2. Read the best seed note and retain its stable `id` or canonical path.
3. Check `/obsidian/graph/projection/status` when graph expansion is useful.
4. Use `alexandria_get_related_notes(note_id=... | path=...)` to inspect related notes.
5. Read and cite the returned notes before using them as evidence.

Durable relationships are owned by source Markdown. PostgreSQL indexed edge state
is rebuildable, while Rust owns deterministic
projection, traversal, and candidate-selection compute. The application keeps a
rebuildable projection cache and does not simulate graph traversal in a second
runtime authority.
Missing or ambiguous targets are reported as counted, non-fatal rebuild issues
and are excluded from the active projection. Use detailed issue output only as a
bounded repair sample, not as the normal graph status payload.

## Advanced exact writes

Treat every update as a read-modify-write operation:

1. Read the current note and retain its `content_hash`.
2. Preserve its stable `id`, canonical path, and applicable scope identity.
3. Send the current hash as `expected_content_hash` when replacing the note.
4. If the backend returns `409 OBSIDIAN_WRITE_CONFLICT`, do not retry blindly.
5. Re-read the note, merge the newer content, and retry with the new hash.

An atomic file replacement prevents partial Markdown, but `expected_content_hash`
prevents one agent from silently overwriting another agent's completed update.

## Strict low-level scope identity

- `AGENT` writes and recall require the intended `agent_id`.
- `SESSION` writes and recall require the intended `session_id`.
- `USER` writes and recall require the intended `user_id`.
- `PROJECT` writes and recall require the intended `project`.
- For project-only Context recall, send both `project="<project>"` and
  `include_scopes=["PROJECT"]`. The REST field is `include_scopes`, not
  `recall_scopes`; using the response-field name in a request fails strict
  validation with HTTP `422`.
- Supply `workspace_id` whenever the caller has one.
- For STRICT/explicit scope requests and Context writes, do not substitute
  `GLOBAL` for a missing required identity; repair the request. AUTO recall may
  independently include its declared GLOBAL fallback and report skipped lanes.
- Keep each concurrent task on its own database/request session.

For strict project-only diagnostics, check `recall_scopes=["PROJECT"]` and the
intended identity boundary. Normal AUTO recall may include declared related
projects and global evidence. HYBRID is required only when proving semantic
readiness; successful source readback remains valid during projection degradation.

When an advanced low-level write changes note links or graph-relevant metadata,
diagnose the returned projection state. If maintenance is required, use:

1. vault reindex;
2. queued embedding reindex when RAG reports missing or stale rows;
3. verify the graph projection returned by vault reindex; explicitly rebuild when it is not current or a diagnostic rebuild is required;
4. exact search/readback plus one related-note lookup from a known seed.

These maintenance steps are sequential. A busy-maintenance conflict requires
waiting for its owner; a CAS conflict requires re-read/merge. After a timeout or
unknown mutation outcome, inspect the returned run/job or exact source before any
retry and keep the original key. Normal search does not implicitly reindex.

## Evidence
- https://github.com/heterarchy-systems/heterarchy-alexandria/blob/main/README.md
- https://github.com/heterarchy-systems/heterarchy-alexandria/blob/main/backend/app/mcp_server/backend_tool_gateway.py

## Related Alexandria skills

- [Operational Sync](../operational-sync/SKILL.md) — load for projection repair.
- [Safe Markdown Storage](../safe-markdown-storage/SKILL.md) — load for exact writes or imports.
