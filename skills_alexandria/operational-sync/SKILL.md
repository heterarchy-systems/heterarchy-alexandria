---
name: operational-sync
description: Use when heterarchy-alexandria needs operational recovery planning, PostgreSQL/Obsidian index synchronization, queued embedding reindex, Neo4j graph projection rebuild, RAG status repair, or proof that library search and optional graph discovery are healthy.
---

# Operational Sync

Use this skill to restore heterarchy-alexandria retrieval health without modifying Obsidian Markdown source notes.

## Invariants

- Treat Obsidian Markdown as the source of truth.
- Treat PostgreSQL FTS, pgvector, embedding rows, and the Neo4j projection as rebuildable cache/index state.
- Runtime persistence is PostgreSQL-only. Do not add or operate a SQLite runtime, compatibility path, fallback, or direct SQLite cleanup procedure.
- Preserve PostgreSQL indexed graph-edge state as projection source cache; do not use it as a graph traversal fallback.
- Treat vault reindex, queued embedding reindex, and graph rebuild as one fail-fast maintenance lane; run them sequentially and retry an HTTP `409` only after the active operation finishes.
- Prefer non-destructive sync first: status check → Obsidian reindex → queued embedding reindex when needed → graph projection rebuild when enabled → verification.
- Use the persisted recovery plan/run workflow before manual repair. Do not mutate PostgreSQL or copy files behind the API.
- Preserve recovery manifests and exact blockers when automatic recovery is not allowed.
- Never hard-delete Obsidian Markdown as part of this procedure.
- Never overwrite the live Vault directly from a browser request.
- Stop only when `/operations/readiness` is `READY` or the remaining blocker is explicitly explained.

## Procedure
1. Read operational readiness, RAG status, graph status, and maintenance queue state before mutating anything.
2. Reindex the canonical Vault when note/index drift exists and treat the returned `graph_projection` as primary graph evidence.
3. Catch up only stale/missing embeddings with bounded `force=false` maintenance jobs unless full recomputation is explicitly required.
4. Recheck graph, queue, RAG, and readiness; stop only when remaining warnings/issues are zero or explicitly bounded and documented.

## Fast path

Run from the repo root unless noted otherwise.

```bash
curl -sS http://127.0.0.1:8000/health/live
curl -sS http://127.0.0.1:8000/obsidian/status | jq
curl -sS http://127.0.0.1:8000/memory/contexts/rag/status | jq
curl -sS http://127.0.0.1:8000/obsidian/graph/projection/status | jq
curl -sS http://127.0.0.1:8000/operations/readiness | jq
```

If `stale_notes>0` or the vault index may be stale:

```bash
curl -sS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

If `embedding=REINDEX_REQUIRED`, `stale_rows>0`, or `missing_rows>0`, use the official queued maintenance path. Do not substitute vault reindex or the legacy synchronous soft-rebuild route for embedding inference:

```bash
job_json="$(
  curl -fsS -X POST \
    http://127.0.0.1:8000/operations/maintenance/embedding-reindex/jobs \
    -H "Content-Type: application/json" \
    --data '{
      "requested_by":"operator",
      "source_id":"operational-sync-manual",
      "limit":1000,
      "force":false
    }'
)"
printf '%s\n' "$job_json" | jq
job_id="$(printf '%s' "$job_json" | jq -r '.job_id')"

completed=false
for _ in $(seq 1 120); do
  state="$(
    curl -fsS \
      "http://127.0.0.1:8000/operations/maintenance/jobs/${job_id}"
  )"
  printf '%s\n' "$state" | jq
  status="$(printf '%s' "$state" | jq -r '.status')"
  case "$status" in
    SUCCEEDED) completed=true; break ;;
    FAILED) exit 1 ;;
    QUEUED|RUNNING|RETRYING) ;;
    *) exit 1 ;;
  esac
  sleep 1
done
[[ "$completed" == true ]] || exit 1

curl -fsS \
  http://127.0.0.1:8000/operations/maintenance/queue/status | jq
curl -fsS \
  http://127.0.0.1:8000/memory/contexts/rag/status | jq
```

Use a stable `source_id` for duplicate suppression and keep `limit` bounded to `1..1000`. Set `force=true` only when matching embeddings must be regenerated, not for ordinary missing/stale repair. Completion requires the job to succeed, queue `pending=0`, `dead_letter_length=0`, and RAG status to report no missing/stale rows with effective `HYBRID` retrieval.

After every vault reindex, re-check RAG status. Vault reindex can create new missing embedding rows, so enqueue another bounded embedding job if needed.

Vault reindex now projects the current indexed graph when Neo4j projection is enabled.
Treat the returned `graph_projection` object as the primary projection result. Run the
dedicated rebuild only when projection is missing, stale, failed, intentionally skipped,
or an explicit diagnostic rebuild is required:

```bash
curl -fsS -X POST \
  http://127.0.0.1:8000/obsidian/graph/projection/rebuild | jq
curl -fsS \
  http://127.0.0.1:8000/obsidian/graph/projection/status | jq
```

Require `status=ready`, `graph_read_model=neo4j`, no errors, and node/edge counts consistent with the
current indexed vault. Read `issue_total`/`issue_counts` from rebuild and
`last_run_issue_total`/`last_run_issue_counts` from status as non-fatal source
diagnostics. Missing or ambiguous targets are excluded from the active graph.
Only when investigating, request a bounded sample with
`?include_issue_details=true&issue_limit=100` (maximum 500). When graph
projection is disabled, skip this step and verify that core RAG remains healthy;
do not fall back to PostgreSQL edge-cache traversal.

For a missing-target detail, use `note_id` as the source note to repair,
`relative_path` as the unresolved target, and `edge_id` as the indexed
source-cache edge identifier.

Normal `/obsidian/search` requests read the current index and do not trigger a
vault-wide reindex. Use `refresh=true` only for an explicit diagnostic refresh;
prefer the dedicated rebuild endpoint for routine synchronization.

## Persisted recovery plan and run

Use this only when readiness reports `RECOVERY_REQUIRED` or another explicit
blocker that the official recovery workflow owns. Start with a read-only plan:

```bash
plan_json="$(
  curl -fsS -X POST \
    http://127.0.0.1:8000/operations/recovery/plan \
    -H "Content-Type: application/json" \
    --data '{"trigger":"manual","actor":"operator"}'
)"
printf '%s\n' "$plan_json" | jq
```

Do not apply when `automatic_execution_allowed` is false. Preserve and report
`blocked_reasons`, `warnings`, `next_actions`, and the source snapshot instead.
When execution is explicitly allowed, reuse the plan's generated idempotency key:

```bash
allowed="$(printf '%s' "$plan_json" | jq -r '.automatic_execution_allowed')"
[[ "$allowed" == true ]] || exit 1
idempotency_key="$(printf '%s' "$plan_json" | jq -r '.idempotency_key')"

run_json="$(
  jq -n \
    --arg key "$idempotency_key" \
    '{trigger:"manual",actor:"operator",idempotency_key:$key}' \
  | curl -fsS -X POST \
      http://127.0.0.1:8000/operations/recovery/runs \
      -H "Content-Type: application/json" \
      --data-binary @-
)"
printf '%s\n' "$run_json" | jq
run_id="$(printf '%s' "$run_json" | jq -r '.id')"

curl -fsS \
  "http://127.0.0.1:8000/operations/recovery/runs/${run_id}" | jq
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
```

Require the persisted run to finish `COMPLETED`, with no `error_code` or
`error_summary`, and require final readiness `READY/HYBRID`. On `BLOCKED` or
`FAILED`, keep the manifest path and exact next actions. Use the dedicated
parent-linked retry endpoint or MCP recovery tool for an intentional retry;
do not mutate PostgreSQL, Redis, or the Vault behind the API, and do not invent
a SQLite recovery path.

The equivalent MCP boundary is:

- `alexandria_recover(dry_run=true, ...)` for diagnosis and planning;
- `alexandria_recover(dry_run=false, idempotency_key=...)` only after the plan
  allows execution;
- `alexandria_recovery_run_status(run_id=...)` for persisted verification.

## Final verification

Readiness must be clean:

```bash
curl -sS http://127.0.0.1:8000/operations/readiness | jq
```

Expected:

```json
{
  "status": "READY",
  "ready": true,
  "warnings": [],
  "blockers": [],
  "next_actions": []
}
```

Run a representative HYBRID search:

```bash
curl -sS -X POST http://127.0.0.1:8000/memory/contexts/retrieval/search \
  -H "Content-Type: application/json" \
  --data '{"query":"운영 안정성 자동 복구 루프","strategy":"HYBRID","limit":3,"project":"heterarchy-alexandria","include_scopes":["PROJECT"]}' | jq
```

Expected:

- `effective_strategy=HYBRID`
- `recall_scopes=["PROJECT"]`
- no warnings
- a relevant Obsidian PRD/context note appears
- vector/semantic retrieval evidence is present

When graph projection is enabled, also verify graph discovery from a known seed:

```bash
curl -fsS -X POST \
  http://127.0.0.1:8000/obsidian/graph/projection/rebuild | jq
curl -fsS \
  "http://127.0.0.1:8000/obsidian/notes/<note-id>/related?limit=5" | jq
```

Expected:

- projection `status=ready` and `graph_read_model=neo4j`;
- rebuild `errors` is empty; any `issue_total` is explained by its counted source diagnostics rather than mistaken for an operation failure;
- each related item exposes its relation, source kind, direction, score, and edge id;
- returned notes can be read back from canonical Obsidian Markdown;
- disabled mode returns 503 for related-note traversal while core RAG remains usable.

## Code repair note

If `/operations/readiness` returns 500 with a Pydantic validation error for `ContextEmbeddingSourceStatusResponse`, fix the interface schema boundary rather than the embedding data:

- Convert `ContextEmbeddingSourceStatus` dataclasses through `source_status_payload()` before Pydantic validation.
- Add/keep a router regression test that asserts `rag.source_statuses` is serialized.
- Run `cd backend && make ci` before claiming completion.

## Related Alexandria skills

- [[Skills/Active/Alexandria Library]] — scoped recall, safe writes, and graph-aware discovery.
- [[Skills/Active/Librarian Operator]] — search-first operation and related-note expansion.
