---
name: operational-sync
description: Use when heterarchy-alexandria needs cause-specific recovery, Vault/index synchronization, bounded embedding maintenance, graph validation, or a scoped readiness proof.
---

# Operational Sync

Use the existing Alexandria read, preview, queue, and recovery surfaces to repair a bounded operational cause and prove the affected capability. Obsidian Markdown remains canonical source storage; PostgreSQL, FTS, pgvector, embedding rows, and the PostgreSQL graph projection are rebuildable runtime state. A healthy index or graph projection does not prove that canonical source storage or the whole Library is healthy.

## Choose the smallest owned path

Start with `alexandria_operational_readiness`. Then use `alexandria_memory_steward_diagnose` when the composed queue, CURRENT Compact, RAG, graph, and DLQ evidence matters. `alexandria_memory_steward_seal` is the final scoped circulation check.

Use the cause-specific owner indicated by the evidence:

- Managed note/index drift: `alexandria_recover(dry_run=true, trigger, actor)` and inspect its planned steps. For frontmatter-only repair, use `alexandria_repair_frontmatter` with `request.path`, `request.expected_content_hash`, `request.replacement_frontmatter`, and `request.preserve_body_bytes=true`. The CAS token is the full raw-document hash from `alexandria_read_note_raw`, not an ordinary body hash. Server-owned fields and redaction placeholders are rejected.
- Raw source replacement: use `alexandria_read_note_raw` first, then `alexandria_repair_note_raw(path, expected_content_hash, raw_content)` only when the full replacement is based on an exact, byte-faithful read. Never turn a masked or non-byte-exact read into canonical Markdown. Preserve unrelated body bytes when the repair is frontmatter-only.
- Embeddings: submit `alexandria_reindex_context_embeddings(requested_by, source_id, limit, force=false)` through the maintenance queue. Keep `limit` within the advertised bound and use a stable `source_id`.
- Graph projection: use `alexandria_get_graph_projection_status`; invoke `alexandria_rebuild_graph_projection` only for a missing, stale, failed, or explicitly requested projection rebuild. Then read status again and use `alexandria_graph_list_issues` for bounded missing/ambiguous link evidence.
- Temporal packet gaps: use `alexandria_temporal_coverage(project, start_date, end_date, families?, not_expected?, timezone?)`. `BACKFILL`, `MISSING`, `OPEN`, and `NOT_EXPECTED` are distinct source states. A `not_expected` entry declares caller calendar policy for that family/date; supply it only with the task's calendar evidence; do not infer a holiday or `NO_CHANGE` from a missing packet.

Graph `issue_total=0` means the current projection has no reported missing/ambiguous target issues. It does not mean orphan debt is zero. Use `alexandria_list_graph_orphans(request={project?, limit<=200, cursor?})`, `alexandria_get_graph_orphan_status(request={note_id})`, and `alexandria_suggest_graph_relations(request={note_id|path, limit<=50})` for orphan debt and evidence-backed suggestions. Suggestions never create notes or relations.

## Recovery preview and apply

A recovery plan is a read-only preview. Use:

```text
alexandria_recover(
  dry_run=true,
  trigger="manual",
  actor="operator"
)
```

Read `steps`, `blocked_reasons`, `source_snapshot`, `plan_hash`, and `automatic_execution_allowed`. Recovery is cause-specific: it may plan managed-frontmatter repair, Vault reindex, bounded embedding continuation, graph revalidation, link diagnostics, CURRENT readiness, or DLQ reconciliation. It must report missing owners or blocked prerequisites instead of manufacturing a no-op repair.

For a requested recovery, when the plan permits apply, reuse the returned `idempotency_key` and exact `plan_hash`:

```text
alexandria_recover(
  dry_run=false,
  trigger="manual",
  actor="operator",
  idempotency_key="<plan.idempotency_key>",
  expected_plan_hash="<plan.plan_hash>"
)
```

The apply fence rejects a changed source snapshot or changed plan. Keep the returned persisted run ID and inspect it with `alexandria_recovery_run_status(run_id)`. A failed or blocked run is evidence: retain its manifest, error code, blockers, and next actions. Do not edit PostgreSQL, Redis, or the Vault behind these boundaries, and do not invent a replacement idempotency key after an unknown response.

A managed frontmatter repair may change the frontmatter fields covered by the plan and exact CAS. It must not rewrite an unrelated body or claim that normal source storage is globally healthy. After a repair, verify the affected source, index, graph/link, embedding, and readiness evidence that the plan actually touched.

## Queue and embedding status

A queued embedding request returns a job identity. Poll the same identity with `alexandria_get_maintenance_job(job_id)` or poll up to fifty identities in one call with `alexandria_get_maintenance_jobs(job_ids=[...])`. Preserve `QUEUED`, `RUNNING`, `RETRYING`, `SUCCEEDED`, `FAILED`, and explicit missing identities. Do not submit a duplicate job because polling timed out or transport returned no response. Completion requires the job to succeed and the affected RAG status to be current.

For bounded recovery continuation, respect the configured batch size and maximum batch count. A max-batch warning means continuation is still required; it is not a successful full repair. Re-read RAG status after Vault reindex because a compile can create new missing or stale embedding rows.

## Compile receipt interpretation

Read `compile_receipt` from operational readiness as a typed state. `NOT_APPLICABLE` means the path did not use the compiler. `OPTIONAL_PRESENT` is available evidence on an optional path. `REQUIRED_AND_PRESENT` means required evidence matches the expected compile plan/policy. `REQUIRED_MISSING`, `INVALID`, and `STALE` are explicit blockers on required paths. Do not interpret `available=false` alone as failure, and do not declare `READY` while required receipt blockers remain.

## Completion boundary

Finish only after the affected operation has durable success evidence and the scoped readiness proof is understood. `READY` is stronger than source readability, index health, graph issue count, or a completed queue job. If residuals remain, report their exact status and owner; do not hide them by broad rebuild, purge, retry, or direct source mutation.
