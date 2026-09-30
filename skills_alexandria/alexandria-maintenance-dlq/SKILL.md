---
name: alexandria-maintenance-dlq
description: Inspect bounded Alexandria maintenance job progress and reconcile lost write responses or dead-letter entries; select safe same-ID retry or provenance-preserving retirement.
---

# Alexandria Maintenance DLQ

Use the existing Redis maintenance lane and PostgreSQL-backed receipt evidence. A DLQ entry is an operational record, not permission to replay blindly.

## Read the batch and entry first

For a circulation with several jobs, use `alexandria_get_maintenance_jobs(job_ids=[...])` with one to fifty existing IDs. It returns known jobs in request order and `missing_job_ids` separately. A missing or expired ID is not a failed job and is not evidence that work can be submitted again.

Review the queue with `alexandria_get_maintenance_queue_status()` and entries with `alexandria_list_maintenance_dead_letters(limit=...)`. Keep the returned `entry_id`, original job identity, attempt history, error summary, and source/effect evidence.

Inspect one entry before choosing an action:

```text
alexandria_maintenance_dlq_inspect(entry_id="<entry_id>")
```

For a batch note-write entry, reconcile its per-item receipts without queue mutation:

```text
alexandria_maintenance_dlq_reconcile(entry_id="<entry_id>")
```

Mutation outcome lookup has two exact selector forms. Use the original receipt key or the direct note-write receipt ID, and supply exactly one selector:

```text
alexandria_get_mutation_outcome(
  request={
    "operation":"note_write",
    "idempotency_key":"<original-key>"
  }
)
```

```text
alexandria_get_mutation_outcome(
  request={
    "operation":"note_write",
    "mutation_id":"<returned note-write: followed by 64 lowercase hex characters>"
  }
)
```

The accepted `operation` values are `verified_upsert`, `relate`, and `note_write`.
Direct mutation-ID lookup is note_write-only; never synthesize a receipt ID.
COMMITTED proves the primary source effect, not all projections. NOT_COMMITTED
with definitive evidence can support retry; CONFLICTED needs source merge. The
receipt status UNKNOWN is distinct from the DLQ class UNKNOWN_OUTCOME.

## Unknown outcomes stop retry

`UNKNOWN_OUTCOME` and `RECONCILIATION_REQUIRED` require source/effect readback and reconciliation. Do not invoke a fresh logical operation, invent a new idempotency key, or use replay to guess whether the original effect committed. A conflicted or unavailable source remains unresolved until its exact evidence is available.

Preview the same-ID retry eligibility before a mutation:

```text
alexandria_maintenance_dlq_retry(
  entry_id="<entry_id>",
  dry_run=true,
  reason="<bounded operator reason>"
)
```

The tool defaults `dry_run` to `false`; always spell `dry_run=true` when requesting a preview. After a definitive retryable preview, an authorized retry uses the same entry with `dry_run=false`. Keep already-COMMITTED batch items intact; do not resubmit them as new writes. Poll the returned job with `alexandria_get_maintenance_job(job_id)` or `alexandria_get_maintenance_jobs(job_ids=[...])` and verify its final result.

`alexandria_replay_maintenance_dead_letter(entry_id="<entry_id>")` creates a fresh job identity for the original request. It is a separate replay authority from same-ID DLQ retry and must be used only when a fresh logical operation is explicitly within the requested authority. A fresh job does not resolve an unknown original effect.

## Retire and purge

When an entry is obsolete, superseded, manually reconciled, invalid-source, non-retryable, or historical residual, preserve the PostgreSQL provenance before removing the live DLQ entry:

```text
alexandria_maintenance_dlq_retire(
  entry_id="<entry_id>",
  reason="<why it is closed>",
  classification="HISTORICAL_RESIDUAL",
  retired_by="<actor>"
)
```

Choose one classification: OBSOLETE, SUPERSEDED, INVALID_SOURCE, MANUAL_RECONCILED,
NON_RETRYABLE or HISTORICAL_RESIDUAL; the example classification is not a combined
enum value. Inspect retired/pending_cleanup/archive_id evidence; failed cleanup
remains pending rather than erasing the retirement record.

Retirement is a per-entry provenance-preserving close. It is different from replay and does not retry effects.

`alexandria_purge_maintenance_dead_letters()` is an explicit bulk administrative retention operation. It drops live DLQ evidence and is not normal cleanup. Use the inspect → outcome/reconcile → same-ID retry or retire flow for ordinary operations.
