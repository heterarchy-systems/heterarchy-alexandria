---
name: operational-sync
description: Use when heterarchy-alexandria needs operational recovery planning, PostgreSQL/Obsidian index synchronization, queued embedding reindex, Rust graph projection rebuild, RAG status repair, or proof that library search and graph discovery are healthy.
---

# Operational Sync

Use this skill to restore heterarchy-alexandria retrieval health without modifying Obsidian Markdown source notes.

## Invariants

- Treat Obsidian Markdown as the source of truth.
- Treat PostgreSQL FTS, pgvector, embedding rows, and the bounded graph projection cache as rebuildable index state; Rust owns deterministic graph projection and traversal compute.
- Runtime persistence is PostgreSQL-only. Do not add or operate a SQLite runtime, compatibility path, fallback, or direct SQLite cleanup procedure.
- Preserve PostgreSQL indexed graph-edge state as the graph source; do not introduce a second graph database or compute authority.
- Run required maintenance sequentially. A classified busy-maintenance conflict may be retried after its owner finishes; CAS conflicts, blocked recovery and unknown outcomes require their own returned next actions.
- Prefer non-destructive sync first: status check → Obsidian reindex → queued embedding reindex when needed → PostgreSQL/Rust graph projection rebuild → verification.
- Use the persisted recovery plan/run workflow before manual repair. Do not mutate PostgreSQL or copy files behind the API.
- Preserve recovery manifests and exact blockers when automatic recovery is not allowed.
- Never hard-delete Obsidian Markdown as part of this procedure.
- Never overwrite the live Vault directly from a browser request.
- Stop only when `/operations/readiness` is `READY` or the remaining blocker is explicitly explained.

## Procedure
1. Read operational readiness/capabilities once, then inspect only the failing subsystem's detailed status. For a single note, prefer `alexandria_verify` with an exact selector when registered.
2. Reindex the canonical Vault when note/index drift exists and treat the returned `graph_projection` as primary graph evidence.
3. Catch up only stale/missing embeddings with bounded `force=false` maintenance jobs unless full recomputation is explicitly required.
4. Recheck graph, queue, RAG, and readiness; stop only when remaining warnings/issues are zero or explicitly bounded and documented.

`alexandria_verify` can return `vector_current=null` or `graph_current=null`.
Those values mean unverified, not current. Consult affected RAG/graph status
before claiming projection freshness; source/readback evidence remains separate.

## Source access during degradation

Index degraded does not mean memory unavailable. If the source is readable,
retain exact note-ID/path/logical-identity access through registered recall/read
tools while repairing only affected projections. Distinguish source revision,
projection revision and freshness; an unknown revision is not proof of staleness.
Source unavailable or uncertain durability requires the returned recovery action,
not another write or an index-only repair claim.

For queued embedding or persisted recovery operations, preserve the original key
and any returned plan/run/job ID after timeout or disconnected transport. Read
durable status before retrying. Synchronous Vault/graph rebuilds may return no
usable operation identity when the response is lost: record UNKNOWN, inspect
current readiness/projection state and active maintenance, and do not infer that
the particular rebuild succeeded from a healthy snapshot alone. Do not blindly
resubmit, reset checkpoints, start competing recovery, or invent a replacement
key. Keep unknown operation outcome separate from currently observed health.

## Fast path

Run from the repo root unless noted otherwise. The examples enable pipeline
failure handling so a failed HTTP call cannot be hidden by successful JSON
formatting. Retain the error and follow the unknown-outcome guidance for writes.

```bash
set -euo pipefail
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/obsidian/status | jq
curl -fsS http://127.0.0.1:8000/memory/contexts/rag/status | jq
curl -fsS http://127.0.0.1:8000/obsidian/graph/projection/status | jq
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
```

If `stale_notes>0` or the vault index may be stale:

```bash
set -euo pipefail
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

If `embedding=REINDEX_REQUIRED`, `stale_rows>0`, or `missing_rows>0`, use the official queued maintenance path. Do not substitute vault reindex or the legacy synchronous soft-rebuild route for embedding inference:

```bash
set -euo pipefail
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
  job_status="$(printf '%s' "$state" | jq -r '.status')"
  case "$job_status" in
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

Use a stable `source_id` for duplicate suppression and keep `limit` bounded to `1..1000`. Set `force=true` only when matching embeddings must be regenerated. If polling expires, retain the job ID and resume status checks; do not submit a duplicate job. Completion requires that job to succeed and the affected RAG rows to be current. Report unrelated queue/dead-letter work separately; do not repair or drain it as part of a single-note save.

After every vault reindex, re-check RAG status. Vault reindex can create new missing embedding rows, so enqueue another bounded embedding job if needed.

Vault reindex now projects the current indexed graph through PostgreSQL and Rust.
Treat the returned `graph_projection` object as the primary projection result. Run the
dedicated rebuild only when projection is missing, stale, failed, intentionally skipped,
or an explicit diagnostic rebuild is required:

```bash
set -euo pipefail
curl -fsS -X POST \
  http://127.0.0.1:8000/obsidian/graph/projection/rebuild | jq
curl -fsS \
  http://127.0.0.1:8000/obsidian/graph/projection/status | jq
```

Require `status=ready`, `graph_read_model=postgresql`, no errors, and node/edge counts consistent with the
current indexed vault. Read `issue_total`/`issue_counts` from rebuild and
`last_run_issue_total`/`last_run_issue_counts` from status as non-fatal source
diagnostics. Missing or ambiguous targets are excluded from the active graph.
Only when investigating, request a bounded sample with
`?include_issue_details=true&issue_limit=100` (maximum 500).

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
set -euo pipefail
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
set -euo pipefail
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
set -euo pipefail
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
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
set -euo pipefail
curl -fsS -X POST http://127.0.0.1:8000/memory/contexts/retrieval/search \
  -H "Content-Type: application/json" \
  --data '{"query":"운영 안정성 자동 복구 루프","strategy":"HYBRID","limit":3,"project":"heterarchy-alexandria","include_scopes":["PROJECT"]}' | jq
```

Expected:

- `effective_strategy=HYBRID`
- `recall_scopes=["PROJECT"]`
- no warnings
- a relevant Obsidian PRD/context note appears
- vector/semantic retrieval evidence is present

When graph discovery is in scope, inspect its status and a known seed. Reuse the
rebuild result already obtained; do not rebuild again solely for verification:

```bash
set -euo pipefail
curl -fsS \
  http://127.0.0.1:8000/obsidian/graph/projection/status | jq
curl -fsS \
  "http://127.0.0.1:8000/obsidian/notes/<note-id>/related?limit=5" | jq
```

Expected:

- projection `status=ready` and `graph_read_model=postgresql`;
- rebuild `errors` is empty; any `issue_total` is explained by its counted source diagnostics rather than mistaken for an operation failure;
- each related item exposes its relation, source kind, direction, score, and edge id;
- returned notes can be read back from canonical Obsidian Markdown;
- related-note traversal reads the active PostgreSQL/Rust projection while core RAG remains usable.

## Implementation failures

If a readiness endpoint fails, retain the typed error or trace and separate a
schema/service defect from projection drift. Do not mutate embeddings to conceal
a serialization error. Repository fixes follow the current AGENTS/Harness and
focused regression evidence; repository closure uses root `make ci`. Operational
checks alone do not prove a source fix or a deployment.

## Related Alexandria skills

- [Alexandria Library](../alexandria-library/SKILL.md) — normal composite memory operations.
