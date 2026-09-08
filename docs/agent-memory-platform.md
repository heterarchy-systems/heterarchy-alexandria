# Agent memory operations

Use the composite operations for ordinary agent work. Existing low-level search,
note, graph, reconciliation and recovery APIs remain useful for diagnostics.
HTTP routes are local operator/backend surfaces; authenticated public access
continues through MCP. These operations do not grant additional permissions.

| Operation | MCP tool | HTTP |
| --- | --- | --- |
| Recall | `alexandria_recall` | `POST /memory/recall` |
| Remember / verified upsert | `alexandria_verified_upsert` | `POST /obsidian/verified-upsert` |
| Verify | `alexandria_verify` | `POST /obsidian/verified-upsert/verify` |
| Relate | `alexandria_relate` | `POST /obsidian/notes/relate` |
| Memory cycle | `alexandria_memory_cycle` | `POST /memory/cycle` |
| Managed specification | `alexandria_execute_managed_spec` | `POST /obsidian/managed-specs/execute` |

MCP accepts a typed `request` argument. Its nested value is the HTTP request body.
The local OpenAPI document and MCP input/output schemas describe the exact fields.

## Recall

```json
{
  "query": "Why did remembered evidence disappear from semantic searches?",
  "project": "Heterarchy Alexandria",
  "related_projects": ["Heterarchy Forge"],
  "scope_mode": "AUTO",
  "limit": 5
}
```

AUTO selects identity lanes that are actually available and records missing lanes
as skipped. STRICT retains the low-level scope validation contract. Related
projects are bounded explicit context; they do not bypass workspace, user or
session isolation. An exact selector accepts one note ID, path or logical identity.

Ordinary Vault notes with no declared scope use PROJECT when a project is present,
or GLOBAL otherwise, consistently in FTS, vector and graph candidate retrieval.
Context notes still require their explicit scope contract; private scopes keep
their identity filters.

The cascade tries exact evidence, lexical/title/alias evidence, semantic retrieval,
related-project expansion and bounded global-scope fallback. Empty FTS stages use
the existing vector lane without repeating lexical work. The result distinguishes
`MATCHED`, `NO_CONFIDENT_MATCH`, `SEARCH_EXHAUSTED` and `DEGRADED_SEARCH`, with stage
trace, actual strategy, affinity and bounded provenance. Graph expansion continues
to use the existing PostgreSQL/Rust retrieval path.

An aware `as_of` timestamp selects historical validity through the existing temporal
authority. Current recall excludes future/superseded state and preserves unresolved
conflict evidence. Unknown authority or projection evidence remains unknown.

## Verified writes and relations

A logical identity consists of `project`, `report`, `date`, `entity` and optional
`edition`. Physical paths and note IDs are resolved by the existing canonical
identity service. Identical logical content replays; replacing different active
content requires its current `expected_content_hash`.

Retain the same idempotency key and immutable request when retrying. A key reused
for different content conflicts. Checkpoints record admission and write progress;
unknown outcomes require exact durable readback. Missing or invalid durable state
must not be converted into a fresh mutation. A completed output changed outside
the operation is a conflict, not permission to overwrite it.

Source durability, readback, metadata/FTS, vector and graph states are separate.
Projection warnings do not mean the Markdown was lost. A source may be stored
while derived projections are pending or unverified; inspect the returned states.

`relate` accepts exact existing source/target note IDs, a typed relation and an
idempotency key. An optional `expected_source_hash` is a complete SHA-256 CAS fence.
It updates source frontmatter and the managed Markdown link section, then checks
indexed edges, graph projection and both related-note directions. Missing targets
are not created. A changed source invalidates a completed relation replay.

## Degraded operations and recovery

Exact note reads reload canonical Markdown, never a cached body. They do not run
reindex. Missing metadata produces `UNINDEXED` and a null index timestamp; changed
source produces stale projection evidence. ID recovery uses bounded source
discovery and refuses incomplete or ambiguous scans.

`GET /operations/capabilities` separately reports source, metadata, FTS, vector,
embedding, graph and reconciliation. Unknown counts/revisions remain null, and an
outage is not treated as proof of revision age. Database-dependent probes stop
after a failed database check while source availability remains observable.

Use the existing recovery plan/run operations referenced by diagnostics. Source
reads stay read-only; mutation and authentication continue to require their own
authorities. Recovery admission and active-record updates are fenced across
processes, with atomic durable record replacement.

## Memory cycle

Request `operation: "dry_run"` with an aware `window_start`, `window_end`, project,
idempotency key and bounded `max_contexts` (at most 100). The preview returns facts,
duplicates, supersession/contradiction/review candidates, Compact changes, relations
and archive candidates without changing source, SQL or checkpoints.

Apply uses `operation: "apply"` and the exact returned `expected_plan_hash` with the
same scope/window. Source or current-Compact changes invalidate the plan. Existing
reconciliation plans/results and Compact lifecycle own the effects. Hard conflicts
and ambiguous supersession remain review-bound. CURRENT Compact authority is
project-scoped; a workspace-only view cannot replace the project-wide CURRENT.
Each phase reports its own outcome because SQL, Markdown and graph writes are
separate effects. Replays verify durable outcomes rather than repeating unknown
mutations.

## Managed specifications

Prepare uses an exact `spec_identity.note_id`, logical date, idempotency key and
execution context containing project, workflow/report, entity and the trusted
`expected_policy_note_id`. Policy/spec paths and titles are navigation metadata.
Missing, inactive, empty, unindexed or conflicting specifications fail before work.

The result contains the exact policy/spec bodies and full version/hash pins in an
inert reference envelope. It does not execute market analysis or elevate Markdown
instructions into permissions. Declared policy/workflow conflicts are rejected;
the caller must keep domain work within the envelope's authorized scope.

Complete supplies the returned envelope hash plus the caller's output. Alexandria
revalidates the pinned sources and persists the logical output through verified
upsert. Completed replay rechecks both specification and output. Provenance retains
full `sha256:` references, including in the stored source and durable checkpoint.

## Evidence boundaries

The implementation matrix, measured costs and executed gates are recorded in
[the implementation plan](plans/2026-09-08-agent-memory-platform.md). Fixture
embedding tests prove PostgreSQL/native routing, not live model quality. Local
schema registration does not imply an already-running deployment or connected
plugin has reloaded the new implementation.
