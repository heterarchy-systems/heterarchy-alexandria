# Memory Compacts Guide 01 — Coverage Window and Rollups

Memory Compacts are durable summaries that help Hermes and Memory Steward resume long-running work without replaying every chat or raw log.

## Recommended window

Use a **24-hour rolling window** as the default range for active project memory compaction.

Recommended policy:

1. Set `covered_from` to the previous compact's `covered_to`.
2. Set `covered_to` to the moment the new compact is written.
3. If the work burst is shorter than 24 hours, compact that session at handoff/end-of-task rather than padding the range.
4. If more than 72 hours passed since the previous compact, start a fresh window from the first meaningful resumed event and mention the gap.
5. Create a separate **7-day weekly rollup** only when daily/session compacts become too granular for recall.

## Why 24 hours?

A 24-hour default is stable because it matches how agent work usually resumes:

- it is short enough to avoid burying decisions under a week of noise;
- it is long enough to capture a full day of implementation, verification, and follow-up;
- it gives agents an unambiguous `covered_from` / `covered_to` range;
- it composes naturally into weekly rollups later.

## When to compact immediately

Compact before the 24-hour window ends when:

- a user explicitly asks for a handoff or summary;
- a long-running coding/research task reaches a coherent checkpoint;
- an implementation decision, bug root cause, or migration state must be preserved;
- a session is ending and future Hermes/Memory Steward runs need restore context.

## What to include

A useful compact should include:

- goal and product context;
- completed work;
- in-progress work and exact next commands;
- key decisions and rejected alternatives;
- verification results;
- risks/gaps;
- source refs to contexts, commits, docs, or issue IDs when available.

Do not include raw secrets, full transcripts, or noisy progress logs.

## Storage contract

Memory Compacts are stored as Obsidian Markdown notes. PostgreSQL owns their
indexed source and lifecycle state; the backend writes notes under:

```text
SERVICE_OBSIDIAN_VAULT_PATH/Alexandria/Memory Compacts/
```

Override the folder with `SERVICE_MEMORY_COMPACT_NOTE_DIR` when the vault needs a different layout. Each note includes YAML frontmatter with `alexandria_type: memory_compact`, stable `id`, lifecycle `status`, coverage timestamps, and source refs.

After manual vault edits, rebuild the PostgreSQL index with the registered MCP
maintenance tool or HTTP route:

```bash
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

Use `alexandria_get_current_memory_compact`,
`alexandria_memory_steward_readiness`, and
`alexandria_memory_steward_refresh_current_compact` for the Memory Steward
lifecycle.
